// ---------------------------------------------------------------------------
// Telemetry Manager - handles FPS tracking, loop lag, WebRTC stats, latency
// calculations, and status polling logs.
// ---------------------------------------------------------------------------

window.updateWaterfallEl = function(id, text) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text;
    if (el.parentElement) {
      el.parentElement.style.opacity = "1.0";
    }
  }
};

window.renderLogEvent = function(logData) {
  if (window.logsPaused) return;
  const logPanel = document.getElementById("log-panel");
  if (!logPanel) return;
  const entry = document.createElement("div");
  entry.className = "log-entry";
  
  const timeSpan = document.createElement("span");
  timeSpan.className = "log-time";
  timeSpan.textContent = new Date().toLocaleTimeString();
  
  const badgeSpan = document.createElement("span");
  const eventName = logData.event.toLowerCase();
  
  let badgeClass = "system";
  if (eventName.includes("error")) badgeClass = "error";
  else if (eventName.includes("barge")) badgeClass = "barge_in";
  else if (eventName.includes("stop") || eventName.includes("abort") || eventName.includes("tts_stopped")) badgeClass = "tts_stopped";
  else if (eventName.includes("stt_final") || eventName.includes("transcript")) badgeClass = "stt_final";
  else if (eventName.includes("llm")) badgeClass = "llm_response";
  
  badgeSpan.className = `log-badge ${badgeClass}`;
  badgeSpan.textContent = logData.event;
  
  const textSpan = document.createElement("span");
  textSpan.className = "log-text";
  textSpan.textContent = typeof logData.detail === "object" ? JSON.stringify(logData.detail) : logData.detail;
  
  entry.appendChild(timeSpan);
  entry.appendChild(badgeSpan);
  entry.appendChild(textSpan);
  
  logPanel.appendChild(entry);
  logPanel.scrollTop = logPanel.scrollHeight;
};

window.updateUIState = function(state, text) {
  if (!window.sessionActive && state !== "disconnected" && state !== "error" && state !== "connecting") {
    console.log("[UI] Ignoring state update to", state, "because session is inactive");
    return;
  }

  const statusBadge = document.getElementById("status-badge");
  const statusDot = document.getElementById("status-dot");
  const waveContainer = document.getElementById("wave-container");
  if (!statusBadge || !statusDot) return;

  statusBadge.textContent = text || state;
  const color = window.statusColors[state.toLowerCase()] || "#3b82f6";
  
  statusBadge.style.color = color;
  statusDot.style.backgroundColor = color;
  statusDot.style.boxShadow = `0 0 12px ${color}`;
  
  if (state === "connected" || state === "speaking") {
    if (waveContainer) waveContainer.classList.add("animating");
    document.querySelectorAll(".wave-bar").forEach(bar => {
      bar.style.backgroundColor = color;
    });
  } else {
    if (waveContainer) waveContainer.classList.remove("animating");
    document.querySelectorAll(".wave-bar").forEach(bar => {
      bar.style.backgroundColor = color;
    });
  }
  
  window.clearStateTimeout();
  window.scheduleStateTimeout(state);
};

window.clearStateTimeout = function() {
  if (window.stateTimeoutId) {
    clearTimeout(window.stateTimeoutId);
    window.stateTimeoutId = null;
  }
};

window.scheduleStateTimeout = function(state) {
  window.clearStateTimeout();
  const t = window.VOICE_CONFIG.state_timeouts || {};
  let ms = 0;
  switch (state) {
    case "speaking": ms = t.speaking_ms || 15000; break;
    case "thinking": ms = t.thinking_ms || 30000; break;
    case "connecting": ms = t.connecting_ms || 15000; break;
    default: ms = 0;
  }
  if (!ms) return;
  window.stateTimeoutId = setTimeout(() => {
    window.renderLogEvent({ event: "system", detail: { msg: `State timeout: stuck in "${state}" for ${ms}ms. Recovering to Listening...` } });
    window.updateUIState("connected", "Listening...");
  }, ms);
};

window.getThresholds = function() {
  const t = window.VOICE_CONFIG && window.VOICE_CONFIG.latency_threshold_targets;
  return {
    stt: (t && t.stt) || 250,
    llm: (t && t.llm) || 800,
    tts: (t && t.tts) || 250,
    network: (t && t.network) || 150,
    total: (t && t.total) || 1200
  };
};

window.setStageState = function(stageId, state, label) {
  const el = window.pipelineEls[stageId] || document.getElementById(stageId);
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
};

window.resetPipeline = function() {
  Object.keys(window.pipelineEls).forEach(key => window.setStageState(key, "idle", key.toUpperCase()));
  window.turnStartTs = performance.now();
};

window.setWaterfall = function(id, label, offsetMs, color) {
  const el = document.getElementById(id);
  if (!el) return;
  const val = offsetMs > 0 ? `+${offsetMs}ms` : "-";
  el.textContent = val;
  el.style.color = color || "#9ca3af";
  if (el.parentElement) {
    el.parentElement.style.opacity = "1.0";
  }
};

window.clearWaterfall = function() {
  ["wf-vad-start", "wf-stt-complete", "wf-orch-start", "wf-llm-first-token", "wf-llm-complete",
   "wf-tts-first-audio", "wf-tts-complete", "wf-playback-start", "wf-playback-end"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = "-";
      el.style.color = "#9ca3af";
      if (el.parentElement) {
        el.parentElement.style.opacity = "0.45";
      }
    }
  });
};

window.pushTelemetryFeed = function(eventType, detail) {
  const telemetryFeed = document.getElementById("telemetry-feed");
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
  text.textContent = typeof detail === "object" ? JSON.stringify(detail) : detail;

  entry.appendChild(time);
  entry.appendChild(badge);
  entry.appendChild(text);
  telemetryFeed.appendChild(entry);
  telemetryFeed.scrollTop = telemetryFeed.scrollHeight;
};

// Calculate percentiles safely
window.calculatePercentile = function(values, percentile) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * percentile / 100;
  const lower = sorted[Math.floor(index)];
  const upper = sorted[Math.min(Math.floor(index) + 1, sorted.length - 1)];
  return Math.round(lower + (upper - lower) * (index - Math.floor(index)));
};

// Polling WebRTC Stats
window.updateWebRTCStats = async function() {
  if (!window.room || window.room.state !== "connected") return;
  const pc = window.room.engine?.client?.peerConnection;
  if (!pc) return;
  try {
    const stats = await pc.getStats();
    let jitter = "-";
    let packetsLost = "-";
    let bitrate = "-";
    stats.forEach(report => {
      if (report.type === "inbound-rtp" && report.kind === "audio") {
        jitter = report.jitter ? (report.jitter * 1000).toFixed(1) + "ms" : "0.0ms";
        packetsLost = report.packetsLost || "0";
        bitrate = report.bytesReceived ? ((report.bytesReceived * 8) / 1000).toFixed(0) + " kbps" : "-";
      }
    });
    const jEl = document.getElementById("webrtc-jitter");
    const lEl = document.getElementById("webrtc-loss");
    const bEl = document.getElementById("webrtc-bitrate");
    if (jEl) jEl.textContent = jitter;
    if (lEl) lEl.textContent = packetsLost;
    if (bEl) bEl.textContent = bitrate;
  } catch (e) {
    console.warn("[WebRTC] Failed fetching connection stats:", e);
  }
};
setInterval(window.updateWebRTCStats, 2000);

// Metrics display row updater
window.updateRow = function(rowId, stats, targetMs) {
  const row = document.getElementById(rowId);
  if (!row) return;
  
  const currCell = row.querySelector(".val-curr");
  const avgCell = row.querySelector(".val-avg");
  const minmaxCell = row.querySelector(".val-minmax");
  const p95p99Cell = row.querySelector(".val-p95p99");
  const statusCell = row.querySelector(".val-status");
  
  if (!currCell) return;
  
  if (stats.curr === 0) {
    currCell.textContent = "-";
    if (avgCell) avgCell.textContent = "-";
    if (minmaxCell) minmaxCell.textContent = "-";
    if (p95p99Cell) p95p99Cell.textContent = "-";
    if (statusCell) statusCell.textContent = "-";
    return;
  }
  
  currCell.textContent = `${stats.curr}ms`;
  if (avgCell) avgCell.textContent = `${stats.avg}ms`;
  if (minmaxCell) minmaxCell.textContent = `${stats.min}ms / ${stats.max}ms`;
  if (p95p99Cell) p95p99Cell.textContent = `${stats.p95}ms / ${stats.p99}ms`;
  
  if (statusCell) {
    if (stats.curr <= targetMs) {
      statusCell.textContent = "🟢";
      currCell.style.color = "#10b981";
    } else if (stats.curr <= targetMs * 1.5) {
      statusCell.textContent = "🟡";
      currCell.style.color = "#f59e0b";
    } else {
      statusCell.textContent = "🔴";
      currCell.style.color = "#ef4444";
    }
  }
};

let healthPollAttempted = false;
window.pollTelemetryData = async function() {
  const url = `http://${window.location.hostname || "localhost"}:${window.API_PORT}/telemetry`;
  try {
    const response = await fetch(url);
    if (!response.ok) {
      healthPollAttempted = true;
      return;
    }
    healthPollAttempted = true;
    const data = await response.json();
    
    const cpuEl = document.getElementById("live-cpu");
    const ramEl = document.getElementById("live-memory");
    if (cpuEl && data.resources) cpuEl.textContent = `${data.resources.cpu}%`;
    if (ramEl && data.resources) ramEl.textContent = `${data.resources.ram} MB`;
    
    const pTokEl = document.getElementById("metrics-prompt-tokens");
    const cTokEl = document.getElementById("metrics-completion-tokens");
    const costEl = document.getElementById("metrics-cost");
    const tpsEl = document.getElementById("live-tokens-sec");
    if (pTokEl && data.tokens) pTokEl.textContent = data.tokens.prompt_tokens;
    if (cTokEl && data.tokens) cTokEl.textContent = data.tokens.completion_tokens;
    if (costEl && data.tokens) costEl.textContent = `$${data.tokens.cost.toFixed(4)}`;
    
    if (data.total && data.total.curr > 0 && data.tokens && data.tokens.completion_tokens > 0) {
      const speed = (data.tokens.completion_tokens / (data.total.curr / 1000)).toFixed(1);
      if (tpsEl) tpsEl.textContent = `${speed} t/s`;
    } else {
      if (tpsEl) tpsEl.textContent = "- t/s";
    }
    
    const updateService = (idPrefix, status) => {
      const dot = document.getElementById(`health-${idPrefix}-dot`);
      const label = document.getElementById(`health-${idPrefix}-status`);
      if (!dot || !label) return;
      
      const healthy = status === "healthy";
      label.textContent = status.toUpperCase();
      label.style.color = healthy ? "#10b981" : "#ef4444";
      dot.style.background = healthy ? "#10b981" : "#ef4444";
      dot.style.boxShadow = healthy ? "0 0 8px #10b981" : "0 0 8px #ef4444";
    };
    
    if (data.services) {
      updateService("api", data.services.api_gateway);
      updateService("redis", data.services.redis);
      updateService("orch", data.services.orchestrator);
      updateService("media", data.services.media_gateway);
    }

    // Push system metrics snapshot for the session metrics download
    if (window.sessionMetricsHistory) {
      const getSafeText = (id) => {
        const el = document.getElementById(id);
        return el ? el.textContent : "-";
      };
      
      window.sessionMetricsHistory.system_snapshots.push({
        timestamp: new Date().toISOString(),
        server_resources: {
          cpu: (data.resources && data.resources.cpu !== undefined) ? `${data.resources.cpu}%` : "-",
          ram: (data.resources && data.resources.ram !== undefined) ? `${data.resources.ram} MB` : "-",
          queue_length: getSafeText("live-queue-length"),
          network_rtt: getSafeText("live-network-rtt")
        },
        webrtc: {
          jitter: getSafeText("webrtc-jitter"),
          packet_loss: getSafeText("webrtc-loss"),
          bitrate: getSafeText("webrtc-bitrate")
        },
        tokens: {
          prompt: (data.tokens && data.tokens.prompt_tokens !== undefined) ? data.tokens.prompt_tokens : "-",
          completion: (data.tokens && data.tokens.completion_tokens !== undefined) ? data.tokens.completion_tokens : "-",
          cost: (data.tokens && data.tokens.cost !== undefined) ? `$${data.tokens.cost.toFixed(4)}` : "-"
        },
        client_diagnostics: {
          dom_nodes: getSafeText("browser-dom"),
          js_heap: getSafeText("browser-heap"),
          fps: getSafeText("browser-fps")
        }
      });
    }
    
    const thresholds = window.getThresholds();
    if (data.llm) window.updateRow("metric-row-llm", data.llm, thresholds.llm || 800);
    if (data.tts) window.updateRow("metric-row-tts", data.tts, thresholds.tts || 250);
    if (data.total) window.updateRow("metric-row-total", data.total, thresholds.total || 1200);
    
    const getLocalStats = (vals) => {
      if (!vals.length) return { curr: 0 };
      return {
        curr: vals[vals.length - 1],
        avg: Math.round(vals.reduce((a, b) => a + b, 0) / vals.length),
        min: Math.min(...vals),
        max: Math.max(...vals),
        p95: window.calculatePercentile(vals, 95),
        p99: window.calculatePercentile(vals, 99)
      };
    };
    
    const localSttStats = getLocalStats(window.localHistory.stt);
    const localNetworkStats = getLocalStats(window.localHistory.network);
    const localInterruptStats = getLocalStats(window.localHistory.interruption);
    
    window.updateRow("metric-row-stt", localSttStats, thresholds.stt || 250);
    window.updateRow("metric-row-network", localNetworkStats, thresholds.network || 150);
    window.updateRow("metric-row-interruption", localInterruptStats, thresholds.interruption || 100);
    
    const bottleneckDiv = document.getElementById("bottleneck-info");
    if (bottleneckDiv) {
      let report = "";
      if (!data.total || data.total.curr === 0) {
        report = "No conversation data analyzed yet. Talk to the agent to start latency profiling!";
      } else {
        const slowStage = (data.llm.curr > data.tts.curr) ? "LLM (Groq)" : "TTS (Cartesia)";
        const slowLat = Math.max(data.llm.curr, data.tts.curr);
        report = `Slowest Stage: ${slowStage} (${slowLat}ms)<br/>`;
        
        const totalTarget = thresholds.total || 1200;
        if (data.total.curr > totalTarget) {
          report += `<span style="color:#ef4444;">🔴 Bottleneck detected. Total turn latency is ${data.total.curr}ms (Target: <${totalTarget}ms).</span><br/>`;
          report += `Suggestion: Configure local semantic caches or restrict LLM generation sizes to speed up response.`;
        } else {
          report += `<span style="color:#10b981;">🟢 System latency is healthy (${data.total.curr}ms).</span>`;
        }
      }
      bottleneckDiv.innerHTML = report;
    }
    
  } catch (err) {
    if (!healthPollAttempted) {
      healthPollAttempted = true;
      window.replaceCheckingStatus();
    }
  }
};
setInterval(window.pollTelemetryData, 2000);

window.replaceCheckingStatus = function() {
  document.querySelectorAll('[id$="-status"]').forEach(el => {
    if (el.textContent === "CHECKING...") {
      const prefix = el.id.replace("-status", "");
      el.textContent = "UNKNOWN";
      el.style.color = "#9ca3af";
      const dot = document.getElementById(prefix + "-dot");
      if (dot) {
        dot.style.background = "#9ca3af";
        dot.style.boxShadow = "none";
      }
    }
  });
};

// Browser performance counters loop
setInterval(() => {
  const domEl = document.getElementById("browser-dom");
  if (domEl) domEl.textContent = document.getElementsByTagName('*').length;
  const heapEl = document.getElementById("browser-heap");
  const mem = window.performance?.memory;
  const heap = mem ? (mem.usedJSHeapSize / (1024 * 1024)).toFixed(1) : "-";
  if (heapEl) heapEl.textContent = heap;
}, 1000);

window.recordTurnMetrics = function(isCancelled = false, reason = "") {
  if (!window.sessionMetricsHistory) return;

  const currentTurnIdx = window.currentTurnIndex || 1;
  // Deduplication guard: do not record the same turn index twice
  if (window.lastRecordedTurnId === currentTurnIdx && !isCancelled) {
    console.log("[Metrics] Skipping duplicate turn recording for turn", currentTurnIdx);
    return;
  }
  window.lastRecordedTurnId = currentTurnIdx;
  const getVal = (id) => {
    const el = document.getElementById(id);
    return el ? el.textContent : "-";
  };
  
  const waterfall = {
    vad_start: getVal("wf-vad-start"),
    stt_complete: getVal("wf-stt-complete"),
    orch_start: getVal("wf-orch-start"),
    llm_first_token: getVal("wf-llm-first-token"),
    llm_complete: getVal("wf-llm-complete"),
    tts_first_audio: getVal("wf-tts-first-audio"),
    tts_complete: getVal("wf-tts-complete") || getVal("wf-tts-first-audio"),
    playback_start: getVal("wf-playback-start"),
    playback_end: getVal("wf-playback-end")
  };

  // Skip if it's an empty record
  if (Object.values(waterfall).every(v => v === "-")) return;

  let userQueryVal = getVal("user-transcript");
  if (userQueryVal === "Listening for your speech...") userQueryVal = "-";
  let agentResponseVal = getVal("agent-response");
  if (agentResponseVal === "Waiting for query...") agentResponseVal = "-";

  const turnIndex = window.sessionMetricsHistory.turn_latency_records.length + 1;
  const istTime = window.formatIST ? window.formatIST() : new Date().toLocaleString();
  const record = {
    turn_index: turnIndex,
    timestamp: istTime,
    timestamp_ist: istTime,
    status: isCancelled ? `cancelled (${reason})` : "completed",
    user_query: userQueryVal,
    agent_response: agentResponseVal,
    waterfall: waterfall,
    stt_finalization: window._sttFinalizationMs || 120,
    stage_timestamps: {
      vad_start: window._vadStartIso || istTime,
      stt_complete: window._sttCompleteIso || istTime,
      llm_first_token: window._llmFirstTokenIso || "-",
      llm_complete: window._llmCompleteIso || "-",
      tts_first_audio: window._ttsFirstAudioIso || "-",
      playback_start: window._playbackStartIso || "-",
      playback_end: window._playbackEndIso || "-"
    }
  };

  window.sessionMetricsHistory.turn_latency_records.push(record);

  // Parse millisecond targets to run threshold comparisons
  const thresholds = window.getThresholds();
  const parseMs = (text) => {
    if (!text || text === "-" || text === "") return null;
    const m = text.match(/\+?(\d+)ms/);
    return m ? parseInt(m[1]) : null;
  };

  const sttOffset = parseMs(waterfall.stt_complete);
  const llm1stOffset = parseMs(waterfall.llm_first_token);
  const llmCompOffset = parseMs(waterfall.llm_complete);
  const tts1stOffset = parseMs(waterfall.tts_first_audio);
  const ttsCompOffset = parseMs(waterfall.tts_complete);
  const playbackStartOffset = parseMs(waterfall.playback_start);

  const addWarning = (metricName, val, threshold, text) => {
    window.sessionMetricsHistory.high_latency_warnings.push({
      timestamp: istTime,
      timestamp_ist: istTime,
      turn_index: turnIndex,
      metric: metricName,
      value: `${val}ms`,
      threshold: `${threshold}ms`,
      message: text
    });
  };

  // Run threshold checks on backend pipeline stage latencies
  if (llm1stOffset !== null && sttOffset !== null) {
    const llmLat = llm1stOffset - sttOffset;
    if (llmLat > thresholds.llm) {
      addWarning("LLM First Token Latency", llmLat, thresholds.llm, `LLM TTFT took ${llmLat}ms (Threshold: ${thresholds.llm}ms)`);
    }
  }
  if (tts1stOffset !== null && llm1stOffset !== null) {
    const ttsLat = tts1stOffset - (llmCompOffset || llm1stOffset);
    if (ttsLat > thresholds.tts) {
      addWarning("TTS Synthesis Latency", ttsLat, thresholds.tts, `TTS synthesis took ${ttsLat}ms (Threshold: ${thresholds.tts}ms)`);
    }
  }
  if (playbackStartOffset !== null && sttOffset !== null) {
    const ttfb = playbackStartOffset - sttOffset;
    if (ttfb > thresholds.total) {
      addWarning("Response Latency (TTFB)", ttfb, thresholds.total, `Total response TTFB took ${ttfb}ms (Threshold: ${thresholds.total}ms)`);
    }
  }
  if (playbackStartOffset !== null && playbackStartOffset > thresholds.total) {
    addWarning("Total Pipeline Latency", playbackStartOffset, thresholds.total, `Total turn latency took ${playbackStartOffset}ms (Threshold: ${thresholds.total}ms)`);
  }
};

window.dispatchTelemetryEvent = function(eventType, detail) {
  console.log(`[TelemetryEvent] ${eventType}`, detail);
  if (eventType === "playback_end") {
    window.recordTurnMetrics(false, "");
  } else if (eventType === "cancellation") {
    window.recordTurnMetrics(true, detail.reason || "interrupted");
  }
};
