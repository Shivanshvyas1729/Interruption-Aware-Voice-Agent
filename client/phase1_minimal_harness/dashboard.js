// ---------------------------------------------------------------------------
// Production-Grade Performance Dashboard & Telemetry
// Captures every pipeline event and renders a live, bottleneck-aware dashboard.
// ---------------------------------------------------------------------------

// --- Pipeline Stage Tracking ---
const pipelineEls = {
  vad: document.getElementById("pipeline-vad"),
  stt: document.getElementById("pipeline-stt"),
  llm: document.getElementById("pipeline-llm"),
  tts: document.getElementById("pipeline-tts"),
  playback: document.getElementById("pipeline-playback")
};

const telemetryFeed = document.getElementById("telemetry-feed");

// Per-turn timestamps (monotonic, offset from turn start)
let turnStartTs = 0;
let sessionMetrics = {
  sttCount: 0,
  llmCount: 0,
  ttsCount: 0,
  turnCount: 0,
  totalTokens: 0,
  totalCost: 0,
  maxQueueLen: 0
};

function getThresholds() {
  const t = window.VOICE_CONFIG && window.VOICE_CONFIG.latency_threshold_targets;
  return {
    stt: (t && t.stt) || 250,
    llm: (t && t.llm) || 800,
    tts: (t && t.tts) || 250,
    network: (t && t.network) || 150,
    total: (t && t.total) || 1200
  };
}

// ---------------------------------------------------------------------------
// Pipeline stage coloring
// ---------------------------------------------------------------------------
function setStageState(stageId, state, label) {
  const el = pipelineEls[stageId] || document.getElementById(stageId);
  if (!el) return;
  const colorMap = {
    idle: { bg: "rgba(255,255,255,0.03)", color: "#9ca3af", text: "\u23F3" },
    active: { bg: "rgba(59,130,246,0.15)", color: "#60a5fa", text: "\u25B6" },
    done: { bg: "rgba(16,185,129,0.15)", color: "#10b981", text: "\u2713" },
    error: { bg: "rgba(239,68,68,0.15)", color: "#ef4444", text: "\u2717" }
  };
  const s = colorMap[state] || colorMap.idle;
  el.style.background = s.bg;
  el.style.color = s.color;
  el.textContent = `${s.text} ${label || stageId.toUpperCase()}`;
}

// ---------------------------------------------------------------------------
// Pipeline reset at start of each turn
// ---------------------------------------------------------------------------
function resetPipeline() {
  Object.keys(pipelineEls).forEach(key => setStageState(key, "idle", key.toUpperCase()));
  turnStartTs = performance.now();
}

// ---------------------------------------------------------------------------
// Waterfall latency display helpers
// ---------------------------------------------------------------------------
function getEl(id) { return document.getElementById(id); }

function setWaterfall(id, label, offsetMs, color) {
  const el = getEl(id);
  if (!el) return;
  const val = offsetMs > 0 ? `+${offsetMs}ms` : "-";
  el.textContent = val;
  el.style.color = color || "#9ca3af";
}

function clearWaterfall() {
  ["wf-vad-start", "wf-stt-complete", "wf-llm-first-token", "wf-llm-complete",
   "wf-tts-first-audio", "wf-playback-start", "wf-playback-end"].forEach(id => {
    const el = getEl(id);
    if (el) { el.textContent = "-"; el.style.color = "#9ca3af"; }
  });
}

// ---------------------------------------------------------------------------
// Delta time since turn start (ms)
// ---------------------------------------------------------------------------
function dt() {
  return turnStartTs > 0 ? Math.round(performance.now() - turnStartTs) : 0;
}

// ---------------------------------------------------------------------------
// Telemetry event feed
// ---------------------------------------------------------------------------
function pushTelemetryFeed(eventType, detail) {
  if (!telemetryFeed) return;
  const entry = document.createElement("div");
  entry.style.display = "flex";
  entry.style.gap = "8px";
  entry.style.alignItems = "center";

  const time = document.createElement("span");
  time.style.color = "rgba(255,255,255,0.3)";
  time.style.minWidth = "65px";
  time.textContent = new Date().toLocaleTimeString();

  const badge = document.createElement("span");
  badge.style.padding = "1px 6px";
  badge.style.borderRadius = "3px";
  badge.style.fontSize = "0.7rem";
  badge.style.fontWeight = "600";
  badge.style.textTransform = "uppercase";

  const typeLower = eventType.toLowerCase();
  if (typeLower.includes("error")) {
    badge.style.background = "rgba(239,68,68,0.2)";
    badge.style.color = "#fca5a5";
  } else if (typeLower.includes("token") || typeLower.includes("ttfb")) {
    badge.style.background = "rgba(168,85,247,0.2)";
    badge.style.color = "#d8b4fe";
  } else if (typeLower.includes("stt")) {
    badge.style.background = "rgba(16,185,129,0.2)";
    badge.style.color = "#6ee7b7";
  } else if (typeLower.includes("llm")) {
    badge.style.background = "rgba(236,72,153,0.2)";
    badge.style.color = "#f9a8d4";
  } else if (typeLower.includes("tts")) {
    badge.style.background = "rgba(245,158,11,0.2)";
    badge.style.color = "#fcd34d";
  } else if (typeLower.includes("cancel") || typeLower.includes("interrupt")) {
    badge.style.background = "rgba(239,68,68,0.2)";
    badge.style.color = "#fca5a5";
  } else {
    badge.style.background = "rgba(255,255,255,0.08)";
    badge.style.color = "#e5e7eb";
  }
  badge.textContent = eventType;

  const text = document.createElement("span");
  text.style.color = "#9ca3af";
  try {
    text.textContent = typeof detail === "object" ? JSON.stringify(detail).slice(0, 80) : String(detail);
  } catch (e) {
    text.textContent = String(detail);
  }

  entry.appendChild(time);
  entry.appendChild(badge);
  entry.appendChild(text);
  telemetryFeed.appendChild(entry);
  telemetryFeed.scrollTop = telemetryFeed.scrollHeight;

  const maxFeed = (window.VOICE_CONFIG && window.VOICE_CONFIG.telemetry_feed_max) || 100;
  while (telemetryFeed.children.length > maxFeed) {
    telemetryFeed.removeChild(telemetryFeed.firstChild);
  }
}

// ---------------------------------------------------------------------------
// Bottleneck analyzer
// ---------------------------------------------------------------------------
function analyzeBottlenecks(latencies) {
  const div = document.getElementById("bottleneck-info");
  if (!div) return;
  if (!latencies || Object.keys(latencies).length === 0) {
    div.innerHTML = "No conversation data analyzed yet. Talk to the agent to start latency profiling!";
    return;
  }

  let report = "";
  const bt = getThresholds();
  const stages = [
    { key: "stt", label: "STT", val: latencies.stt, target: bt.stt },
    { key: "llm", label: "LLM (Groq)", val: latencies.llm, target: bt.llm },
    { key: "tts", label: "TTS (Cartesia)", val: latencies.tts, target: bt.tts }
  ];

  const valid = stages.filter(s => s.val > 0);
  if (valid.length === 0) {
    div.innerHTML = "Waiting for pipeline data...";
    return;
  }

  const slowest = valid.reduce((a, b) => (a.val > b.val ? a : b));
  report = `Slowest Stage: <strong>${slowest.label}</strong> (${slowest.val}ms)<br/>`;

  valid.forEach(s => {
    const pct = Math.round((s.val / slowest.val) * 100);
    const color = s.val <= s.target ? "#10b981" : s.val <= s.target * 1.5 ? "#f59e0b" : "#ef4444";
    report += `<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">
      <span style="min-width:100px;">${s.label}:</span>
      <div style="flex:1;height:8px;background:rgba(255,255,255,0.06);border-radius:4px;overflow:hidden;">
        <div style="width:${pct}%;height:100%;background:${color};border-radius:4px;"></div>
      </div>
      <span style="color:${color};min-width:60px;text-align:right;">${s.val}ms</span>
    </div>`;
  });

  if (latencies.total > bt.total) {
    report += `<div style="margin-top:8px;"><span style="color:#ef4444;">🔴 Bottleneck detected. Total: ${latencies.total}ms (target < ${bt.total}ms).</span></div>`;
  } else if (latencies.total > 0) {
    report += `<div style="margin-top:8px;"><span style="color:#10b981;">🟢 System healthy (${latencies.total}ms).</span></div>`;
  }

  div.innerHTML = report;
}

// ---------------------------------------------------------------------------
// WebSocket Telemetry Consumer
// ---------------------------------------------------------------------------
let telemetryWs = null;
let telemetryReconnectTimer = null;

function connectTelemetry() {
  if (telemetryWs && telemetryWs.readyState === WebSocket.OPEN) return;

  const apiPort = (window.VOICE_CONFIG && window.VOICE_CONFIG.api_port) || 8003;
  const wsUrl = `ws://${window.location.hostname || "localhost"}:${apiPort}/ws/telemetry`;
  telemetryWs = new WebSocket(wsUrl);

  telemetryWs.onopen = () => {
    console.log("[TelemetryDashboard] Connected to telemetry stream");
    if (telemetryReconnectTimer) {
      clearTimeout(telemetryReconnectTimer);
      telemetryReconnectTimer = null;
    }
  };

  telemetryWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleTelemetryEvent(msg);
    } catch (e) {
      console.warn("[TelemetryDashboard] Failed to parse event:", e);
    }
  };

  telemetryWs.onclose = () => {
    console.warn("[TelemetryDashboard] Disconnected. Reconnecting in 3s...");
    telemetryWs = null;
    const reconnDelay = (window.VOICE_CONFIG && window.VOICE_CONFIG.ws_reconnect_delay_ms) || 3000;
    telemetryReconnectTimer = setTimeout(connectTelemetry, reconnDelay);
  };

  telemetryWs.onerror = (e) => {
    console.error("[TelemetryDashboard] WS error:", e);
    telemetryWs.close();
  };
}

// ---------------------------------------------------------------------------
// Per-event-type dispatcher
// ---------------------------------------------------------------------------
function handleTelemetryEvent(msg) {
  const type = msg.type || "";
  const data = msg.data || {};
  const ts = msg.ts || 0;
  const sessionId = msg.session_id || "";
  const turnId = msg.turn_id || "";

  // Only process events for our session
  if (sessionId && !sessionId.includes(window.sessionId || "")) return;

  switch (type) {
    // ---- VAD / STT ----
    case "vad_start":
      setStageState("vad", "active", "VAD");
      break;

    case "vad_final":
    case "stt_final":
      resetPipeline();
      setStageState("vad", "done", "VAD");
      setStageState("stt", "done", "STT");
      const sttWf = data.latency_ms || dt();
      setWaterfall("wf-stt-complete", "STT", sttWf, "#10b981");
      sessionMetrics.sttCount++;
      pushTelemetryFeed(type, data);
      break;

    // ---- LLM ----
    case "llm_request":
      resetPipeline();
      clearWaterfall();
      setStageState("vad", "done", "VAD");
      setStageState("stt", "done", "STT");
      setStageState("llm", "active", "LLM");
      pushTelemetryFeed(type, data);
      break;

    case "llm_first_token":
      setStageState("llm", "active", "LLM");
      const ttfb = data.latency_ms || dt();
      setWaterfall("wf-llm-first-token", "TTFB", ttfb, "#a855f7");
      const ttfbEl = getEl("llm-ttfb");
      if (ttfbEl) ttfbEl.textContent = `${ttfb}ms`;
      pushTelemetryFeed(type, { ttfb_ms: ttfb });
      break;

    case "llm_complete":
      setStageState("llm", "done", "LLM");
      const llmLate = data.latency_ms || dt();
      setWaterfall("wf-llm-complete", "LLM", llmLate, "#ec4899");
      const latencyEl = getEl("llm-latency");
      if (latencyEl) latencyEl.textContent = `${llmLate}ms`;
      const modelEl = getEl("llm-model");
      if (modelEl) modelEl.textContent = data.provider || "groq";
      sessionMetrics.llmCount++;
      pushTelemetryFeed(type, { latency_ms: llmLate });
      break;

    case "llm_tokens":
      const tokPerSec = data.tokens_per_sec || 0;
      const tokCount = data.token_count || 0;
      const tokEl = getEl("live-tokens-sec");
      if (tokEl && tokPerSec > 0) tokEl.textContent = `${tokPerSec} t/s`;
      const tokensEl = getEl("llm-tokens");
      if (tokensEl) tokensEl.textContent = tokCount;
      sessionMetrics.totalTokens += tokCount;
      pushTelemetryFeed(type, { tokens: tokCount, tps: tokPerSec });
      break;

    // ---- TTS ----
    case "tts_start":
      setStageState("tts", "active", "TTS");
      setWaterfall("wf-tts-first-audio", "TTS", dt(), "#f59e0b");
      pushTelemetryFeed(type, data);
      break;

    case "tts_chunk":
      setStageState("tts", "active", "TTS");
      break;

    case "tts_complete":
      setStageState("tts", "done", "TTS");
      const ttsLate = data.latency_ms || dt();
      // Only update if larger than existing
      const existing = getEl("wf-tts-first-audio");
      if (existing && existing.textContent === "-") {
        setWaterfall("wf-tts-first-audio", "TTS", ttsLate, "#f59e0b");
      }
      sessionMetrics.ttsCount++;
      pushTelemetryFeed(type, { latency_ms: ttsLate });
      break;

    // ---- Playback ----
    case "playback_start":
      setStageState("playback", "active", "Playback");
      setWaterfall("wf-playback-start", "Playback", dt(), "#10b981");
      pushTelemetryFeed(type, data);
      break;

    case "playback_end":
      setStageState("playback", "done", "Playback");
      setWaterfall("wf-playback-end", "End", dt(), "#ef4444");
      pushTelemetryFeed(type, data);
      break;

    case "turn_complete":
      sessionMetrics.turnCount++;
      const totalLat = data.total_latency_ms || 0;
      // Update total waterfall if playback-end wasn't set
      const endEl = getEl("wf-playback-end");
      if (endEl && endEl.textContent === "-") {
        setWaterfall("wf-playback-end", "Total", dt(), "#ef4444");
      }
      // Analyze bottlenecks
      analyzeBottlenecks({
        stt: parseInt((getEl("wf-stt-complete") || {}).textContent || "0"),
        llm: parseInt((getEl("wf-llm-complete") || {}).textContent || "0"),
        tts: parseInt((getEl("wf-tts-first-audio") || {}).textContent || "0"),
        total: totalLat
      });
      pushTelemetryFeed(type, { total_ms: totalLat });
      break;

    // ---- Cancellation / Interrupt ----
    case "cancellation":
      setStageState("playback", "idle", "Cancelled");
      pushTelemetryFeed(type, data);
      // Pipeline reset happens on next turn
      break;

    // ---- Token Usage & Billing ----
    case "token_usage":
      const pTok = data.prompt_tokens || 0;
      const cTok = data.completion_tokens || 0;
      const cumPrompt = data.cumulative_prompt || 0;
      const cumComp = data.cumulative_completion || 0;
      const cost = data.cumulative_cost || 0;
      const pEl = getEl("metrics-prompt-tokens");
      const cEl = getEl("metrics-completion-tokens");
      const costEl = getEl("metrics-cost");
      if (pEl) pEl.textContent = cumPrompt;
      if (cEl) cEl.textContent = cumComp;
      if (costEl) costEl.textContent = `$${cost.toFixed(4)}`;
      sessionMetrics.totalCost = cost;
      pushTelemetryFeed(type, { prompt: pTok, completion: cTok });
      break;

    // ---- Queue length ----
    case "queue_update":
      const qLen = data.length || 0;
      const qEl = getEl("live-queue-length");
      if (qEl) qEl.textContent = qLen;
      if (qLen > sessionMetrics.maxQueueLen) sessionMetrics.maxQueueLen = qLen;
      break;

    // ---- CPU / Memory (from server telemetry) ----
    case "resource_usage":
      const cpuEl = getEl("live-cpu");
      const memEl = getEl("live-memory");
      if (cpuEl && data.cpu !== undefined) cpuEl.textContent = `${data.cpu}%`;
      if (memEl && data.ram !== undefined) memEl.textContent = data.ram;
      break;

    case "network_rtt":
      const netEl = getEl("live-network-rtt");
      if (netEl && data.rtt !== undefined) netEl.textContent = `${data.rtt}ms`;
      break;

    default:
      // Unknown events still appear in the feed
      if (type && !type.startsWith("auth_") && !type.startsWith("state_")) {
        pushTelemetryFeed(type, data);
      }
      break;
  }
}

// ---------------------------------------------------------------------------
// Global dispatch - called by app.js for frontend-originated events
// ---------------------------------------------------------------------------
window.dispatchTelemetryEvent = function(type, data) {
  handleTelemetryEvent({ type, data, ts: Date.now() / 1000 });
  // Also forward to WebSocket if open
  if (telemetryWs && telemetryWs.readyState === WebSocket.OPEN) {
    telemetryWs.send(JSON.stringify({ type, data }));
  }
};

// ---------------------------------------------------------------------------
// Integrate with app.js session lifecycle
// ---------------------------------------------------------------------------
// The dashboard gets the sessionId from the global window object
// set by app.js or we listen for it
(function init() {
  // Start telemetry connection
  connectTelemetry();

  // Expose session ID bridge
  const origConnect = window.connectToRoom;
  if (origConnect) {
    const wrapped = async function(token, livekitUrl) {
      resetPipeline();
      return origConnect.call(this, token, livekitUrl);
    };
    window.connectToRoom = wrapped;
  }

  // Periodically push browser resource usage to the feed
  setInterval(() => {
    const cpuEl = getEl("live-cpu");
    const memEl = getEl("live-memory");
    if (cpuEl && cpuEl.textContent === "-") {
      cpuEl.textContent = "0%";
    }
    if (memEl && memEl.textContent === "-") {
      memEl.textContent = "0";
    }
    // Update DOM count
    const domEl = document.getElementById("browser-dom");
    if (domEl) domEl.textContent = document.getElementsByTagName('*').length;

    const heapEl = document.getElementById("browser-heap");
    if (heapEl) {
      const mem = window.performance?.memory;
      heapEl.textContent = mem ? (mem.usedJSHeapSize / (1024 * 1024)).toFixed(1) : "-";
    }
  }, (window.VOICE_CONFIG && window.VOICE_CONFIG.browser_resource_interval_ms) || 5000);
})();
