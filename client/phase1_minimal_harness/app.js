// ---------------------------------------------------------------------------
// Configuration loader — fetches tunable values from /config endpoint
// ---------------------------------------------------------------------------
const VOICE_CONFIG = {};
const API_PORT = 8003;
const CFG_URL = `http://${window.location.hostname || "localhost"}:${API_PORT}/config`;

async function loadVoiceConfig() {
  try {
    const r = await fetch(CFG_URL);
    if (r.ok) Object.assign(VOICE_CONFIG, await r.json());
    console.log("[Config] Voice config loaded:", VOICE_CONFIG);
  } catch (e) {
    console.warn("[Config] Could not load voice config, using defaults:", e.message);
  }
  // Populate table target cells
  const t = VOICE_CONFIG.latency_threshold_targets || {};
  const q = (sel) => document.querySelector(sel);
  if (q(".target-stt")) q(".target-stt").textContent = (t.stt || 250) + "ms";
  if (q(".target-llm")) q(".target-llm").textContent = (t.llm || 800) + "ms";
  if (q(".target-tts")) q(".target-tts").textContent = (t.tts || 250) + "ms";
  if (q(".target-network")) q(".target-network").textContent = (t.network || 150) + "ms";
  if (q(".target-interruption")) q(".target-interruption").textContent = (t.interruption || 100) + "ms";
  if (q(".target-total")) q(".target-total").textContent = (t.total || 1200) + "ms";
}
loadVoiceConfig();

const joinBtn = document.getElementById("join-btn");
const statusBadge = document.getElementById("status-badge");
const statusDot = document.getElementById("status-dot");
const waveContainer = document.getElementById("wave-container");
const logPanel = document.getElementById("log-panel");
const audioEl = document.getElementById("agent-audio");

// Transcript UI elements
const userTranscriptDiv = document.getElementById("user-transcript");
const agentResponseDiv = document.getElementById("agent-response");

// Dashboard UI elements
const toggleDashboardBtn = document.getElementById("toggle-dashboard-btn");
const metricsPanel = document.getElementById("metrics-panel");

// Sidebar controls
const muteBtn = document.getElementById("ctrl-mute-btn");
const unmuteBtn = document.getElementById("ctrl-unmute-btn");
const sttToggleBtn = document.getElementById("ctrl-stt-toggle-btn");
const sttStartBtn = document.getElementById("ctrl-stt-start-btn");
const cancelBtn = document.getElementById("ctrl-cancel-btn");
const resetBtn = document.getElementById("ctrl-reset-btn");
const reconnectBtn = document.getElementById("ctrl-reconnect-btn");
const shutdownBtn = document.getElementById("ctrl-shutdown-btn");
let sttEnabled = true;

// Consistent sessionId for backend tracking
const sessionId = "session-" + Math.random().toString(36).substring(2, 9);
window.sessionId = sessionId;
const roomName = "demo-room";

let room;
let recognition;
let currentAudio = null;

// -----------------------------------------------------------------------
// SESSION ACTIVE FLAG — independent of LiveKit connection state
// -----------------------------------------------------------------------
let sessionActive = false;

// High-precision timestamps for latency waterfall
let speechStartTime = 0;
let timeSTTComplete = 0;
let timeOrchStart = 0;

// Local latency tracking histories
const localHistory = {
  stt: [],
  network: [],
  interruption: []
};

// Web Audio resources for microphone levels
let audioContextForMic = null;
let analyserNode = null;
let micStream = null;
let micEnergyInterval = null;

// CSS variable mappings for dynamic colors
const statusColors = {
  disconnected: "#3b82f6",
  connecting: "#f59e0b",
  connected: "#10b981",
  error: "#ef4444",
  speaking: "#ec4899",
  thinking: "#a855f7"
};

let stateTimeoutId = null;

function getStateTimeout(state) {
  const t = VOICE_CONFIG.state_timeouts || {};
  switch (state) {
    case "speaking": return t.speaking_ms || 15000;
    case "thinking": return t.thinking_ms || 30000;
    case "connecting": return t.connecting_ms || 15000;
    default: return 0;
  }
}

function clearStateTimeout() {
  if (stateTimeoutId) {
    clearTimeout(stateTimeoutId);
    stateTimeoutId = null;
  }
}

function scheduleStateTimeout(state) {
  clearStateTimeout();
  const ms = getStateTimeout(state);
  if (!ms) return;
  stateTimeoutId = setTimeout(() => {
    renderLogEvent({ event: "system", detail: { msg: `State timeout: stuck in "${state}" for ${ms}ms. Recovering to Listening...` } });
    updateUIState("connected", "Listening...");
  }, ms);
}

function calculatePercentile(values, percentile) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = (sorted.length - 1) * percentile / 100;
  const lower = sorted[Math.floor(index)];
  const upper = sorted[Math.min(Math.floor(index) + 1, sorted.length - 1)];
  return Math.round(lower + (upper - lower) * (index - Math.floor(index)));
}

function updateUIState(state, text) {
  statusBadge.textContent = text || state;
  const color = statusColors[state.toLowerCase()] || "#3b82f6";
  
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
  
  clearStateTimeout();
  scheduleStateTimeout(state);
}

function renderLogEvent(logData) {
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
}

// -----------------------------------------------------------------------
// MICROPHONE LEVEL ANALYSER (WEB AUDIO API)
// -----------------------------------------------------------------------
function startMicEnergyTracker(stream) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    audioContextForMic = new AudioCtx();
    const source = audioContextForMic.createMediaStreamSource(stream);
    analyserNode = audioContextForMic.createAnalyser();
    analyserNode.fftSize = (VOICE_CONFIG.ui && VOICE_CONFIG.ui.analyser_fft_size) || 256;
    source.connect(analyserNode);
    
    const bufferLength = analyserNode.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    
    micEnergyInterval = setInterval(() => {
      if (!analyserNode) return;
      analyserNode.getByteTimeDomainData(dataArray);
      
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        const val = (dataArray[i] - 128) / 128;
        sum += val * val;
      }
      const rms = Math.sqrt(sum / bufferLength);
      const cap = VOICE_CONFIG.volume_percent_cap || 100;
      const mult = VOICE_CONFIG.volume_rms_multiplier || 400;
      const volumePercent = Math.min(cap, Math.round(rms * mult));
      const energyBar = document.getElementById("mic-energy-bar");
      if (energyBar) {
        energyBar.style.width = `${volumePercent}%`;
      }
    }, (VOICE_CONFIG.ui && VOICE_CONFIG.ui.mic_energy_interval_ms) || 50);
  } catch (e) {
    console.warn("[MicTracker] Could not start Web Audio analyser for mic energy:", e);
  }
}

function stopMicEnergyTracker() {
  if (micEnergyInterval) {
    clearInterval(micEnergyInterval);
    micEnergyInterval = null;
  }
  if (audioContextForMic) {
    try {
      audioContextForMic.close();
    } catch (e) {}
    audioContextForMic = null;
  }
  analyserNode = null;
  const energyBar = document.getElementById("mic-energy-bar");
  if (energyBar) {
    energyBar.style.width = "0%";
  }
}

// Start analysis stream on microphone access
navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  }
})
  .then(stream => {
    micStream = stream;
    startMicEnergyTracker(stream);
    console.log("[Mic] Microphone access granted");
  })
  .catch(err => {
    console.warn("[Mic] Microphone analysis initialization bypassed:", err.message);
  });

// -----------------------------------------------------------------------
// AUDIO PLAYBACK GATES
// -----------------------------------------------------------------------
function playBase64Audio(base64Data) {
  console.log("[Audio] playBase64Audio called, data length:", base64Data.length);
  try {
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
    }
    
    const binaryString = window.atob(base64Data);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    
    const blob = new Blob([bytes.buffer], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    currentAudio = new Audio(url);
    
    currentAudio.onplay = () => {
      console.log("[Audio] Playback started");
      renderLogEvent({ event: "playback_started", detail: { source: "base64_wav" } });
      updateUIState("speaking", "Speaking...");
      
      if (window.dispatchTelemetryEvent) {
        window.dispatchTelemetryEvent("playback_start", {});
      }
      
      // Mark playback start in waterfall
      if (speechStartTime > 0) {
        const playbackStart = Math.round(performance.now() - speechStartTime);
        const el = document.getElementById("wf-playback-start");
        if (el) el.textContent = `+${playbackStart}ms`;
      }
    };
    
    currentAudio.onended = () => {
      console.log("[Audio] Playback ended");
      renderLogEvent({ event: "playback_completed", detail: { source: "base64_wav" } });
      updateUIState("connected", "Listening...");
      currentAudio = null;
      if (window.dispatchTelemetryEvent) {
        window.dispatchTelemetryEvent("playback_end", {});
      }
    };
    
    currentAudio.onerror = (e) => {
      console.error("[Audio] Audio element error:", e);
      renderLogEvent({ event: "error", detail: { message: `Audio element error: ${e.type}` } });
      updateUIState("connected", "Listening...");
    };
    
    const playPromise = currentAudio.play();
    if (playPromise !== undefined) {
      playPromise.catch(err => {
        console.error("[Audio] Audio playback failed (autoplay policy?):", err.message);
        renderLogEvent({ event: "error", detail: { message: `Audio playback failed: ${err.message}. Click the page to allow audio.` } });
        updateUIState("connected", "Listening...");
      });
    }
  } catch (e) {
    console.error("[Audio] Failed to decode base64 audio:", e);
    renderLogEvent({ event: "error", detail: { message: `Failed to decode TTS audio: ${e.message}` } });
    updateUIState("connected", "Listening...");
  }
}

async function notifyBargeIn() {
  stopAllQueuedAudio();
  if (streamSocket && streamSocket.readyState === WebSocket.OPEN) {
    streamSocket.send(JSON.stringify({
      type: "cancel",
      session_id: sessionId,
      reason: "vad_interrupted"
    }));
  }
  const cancelUrl = `http://${window.location.hostname || "localhost"}:${API_PORT}/control/cancel`;
  try {
    await fetch(cancelUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        reason: "vad_interrupted"
      })
    });
    renderLogEvent({ event: "barge_in", detail: { msg: "Barge-in cancellation dispatched to Gateway." } });
  } catch (e) {
    console.error("[BargeIn] Failed to notify gateway of barge-in:", e);
  }
}

// -----------------------------------------------------------------------
// SPEECH RECOGNITION (STT)
// -----------------------------------------------------------------------
function startSpeechRecognition() {
  console.log("[STT] Starting speech recognition...");
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    const msg = "SpeechRecognition is not supported in this browser. Please use Chrome or Edge.";
    renderLogEvent({ event: "error", detail: { message: msg } });
    console.error("[STT]", msg);
    return;
  }
  
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = false;
  recognition.lang = VOICE_CONFIG.stt_language || 'en-US';
  
  recognition.onstart = () => {
    console.log("[STT] Recognition started — listening for speech");
    renderLogEvent({ event: "stt_started", detail: { msg: "Speech recognition active. Speak into your mic!" } });
    updateUIState("connected", "Listening...");
  };
  
  recognition.onspeechstart = () => {
    const interruptStart = performance.now();
    speechStartTime = performance.now();
    console.log("[STT] Speech detected (VAD start)");
    renderLogEvent({ event: "vad_start", detail: { msg: "Speech detected" } });
    
    // Clear waterfall view for new turn safely
    const ids = ["wf-vad-start", "wf-stt-complete", "wf-llm-first-token", "wf-llm-complete", "wf-tts-first-audio", "wf-playback-start", "wf-playback-end", "wf-orch-start", "wf-tts-complete"];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = "-";
    });
    
    const vadStart = Math.round(performance.now() - speechStartTime);
    const el = document.getElementById("wf-vad-start");
    if (el) el.textContent = `+${vadStart}ms`;
    
    if (window.dispatchTelemetryEvent) {
      window.dispatchTelemetryEvent("vad_start", {});
    }
    
    if (currentAudio) {
      console.log("[STT] Speech detected — interrupting active audio");
      currentAudio.pause();
      currentAudio = null;
      updateUIState("connected", "Listening...");
      
      const interruptLatency = Math.round(performance.now() - interruptStart);
      localHistory.interruption.push(interruptLatency);
      
      renderLogEvent({ event: "barge_in", detail: { msg: `Speech detected: Interrupted playback in ${interruptLatency}ms.` } });
      notifyBargeIn();
    }
  };
  
  recognition.onresult = async (event) => {
    const sttEndTime = performance.now();
    const transcript = event.results[event.results.length - 1][0].transcript.trim();
    if (!transcript) return;
    
    const fallbackStt = VOICE_CONFIG.fallback_stt_latency || 180;
    const sttLatency = speechStartTime > 0 ? Math.round(sttEndTime - speechStartTime) : fallbackStt;
    localHistory.stt.push(sttLatency);
    
    console.log(`[STT] Final transcript: "${transcript}" (STT latency: ${sttLatency}ms)`);
    
    // Update STT waterfall safely
    const elStt = document.getElementById("wf-stt-complete");
    if (elStt) elStt.textContent = `+${sttLatency}ms`;
    
    userTranscriptDiv.textContent = transcript;
    renderLogEvent({ event: "stt_final", detail: { text: transcript, latency_ms: sttLatency } });
    
    updateUIState("thinking", "Thinking...");
    
    const startFetch = performance.now();
    if (speechStartTime === 0) speechStartTime = startFetch;
    timeOrchStart = Math.round(startFetch - speechStartTime);
    const elOrch = document.getElementById("wf-orch-start") || document.getElementById("wf-vad-start");
    if (elOrch) elOrch.textContent = `+${timeOrchStart}ms`;

    // -------------------------------------------------------
    // Path A: WebSocket pipeline (preferred — streaming audio)
    // -------------------------------------------------------
    if (streamSocket && streamSocket.readyState === WebSocket.OPEN) {
      console.log("[WS] Sending transcript via WebSocket pipeline");
      renderLogEvent({ event: "llm_request_sent", detail: { path: "websocket", text: transcript.slice(0, 60) } });
      streamSocket.send(JSON.stringify({
        type: "transcript",
        session_id: sessionId,
        text: transcript
      }));
      return;
    }

    // -------------------------------------------------------
    // Path B: REST /chat fallback
    // -------------------------------------------------------
    console.log("[REST] WebSocket not available, falling back to /chat REST endpoint");
    renderLogEvent({ event: "llm_request_sent", detail: { path: "rest", text: transcript.slice(0, 60) } });
    const chatUrl = `http://${window.location.hostname || "localhost"}:${API_PORT}/chat`;
    try {
      const response = await fetch(chatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          text: transcript
        })
      });
      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`HTTP ${response.status}: ${errText}`);
      }
      const data = await response.json();
      const endFetch = performance.now();
      
      const totalFetchDuration = Math.round(endFetch - startFetch);
      const backendDuration = data.total_latency || 0;
      const networkRTT = Math.max(5, totalFetchDuration - backendDuration);
      localHistory.network.push(networkRTT);
      
      console.log(`[REST] Reply received: "${data.reply}" | LLM: ${data.llm_latency}ms | TTS: ${data.tts_latency}ms | Audio: ${data.audio ? data.audio.length : 0} chars`);
      renderLogEvent({ event: "llm_response", detail: { text: data.reply, llm_ms: data.llm_latency, tts_ms: data.tts_latency } });
      
      // Update LLM/TTS waterfall timestamps using backend-latency fields
      const llmLate = data.llm_latency || 0;
      const ttsLate = data.tts_latency || 0;
      const llmFinish = timeOrchStart + llmLate;
      const ttsFinish = timeOrchStart + llmLate + ttsLate;
      const elLlm = document.getElementById("wf-llm-complete");
      if (elLlm) elLlm.textContent = `+${llmFinish}ms`;
      const elTts = document.getElementById("wf-tts-complete") || document.getElementById("wf-tts-first-audio");
      if (elTts) elTts.textContent = `+${ttsFinish}ms`;
      
      agentResponseDiv.textContent = data.reply;
      
      if (data.audio && data.audio.length > 0) {
        console.log("[REST] TTS audio received, playing...");
        renderLogEvent({ event: "tts_audio_received", detail: { bytes_b64: data.audio.length } });
        playBase64Audio(data.audio);
      } else {
        console.warn("[REST] No audio in response. tts_error:", data.tts_error);
        if (data.tts_error) {
          renderLogEvent({ event: "error", detail: { message: `TTS failed: ${data.tts_error}` } });
        }
        updateUIState("connected", "Listening...");
      }
    } catch (err) {
      console.error("[REST] Turn fetch failed:", err);
      renderLogEvent({ event: "error", detail: { message: `Voice processing failed: ${err.message}` } });
      updateUIState("connected", "Listening...");
    }
  };
  
  recognition.onerror = (e) => {
    if (e.error !== 'no-speech') {
      console.error("[STT] Recognition error:", e.error);
      renderLogEvent({ event: "error", detail: { message: `Speech recognition error: ${e.error}` } });
    }
  };
  
  recognition.onend = () => {
    console.log("[STT] Recognition ended. sessionActive:", sessionActive, "sttEnabled:", sttEnabled);
    // Restart STT as long as the session is active — independent of LiveKit state
    if (sttEnabled && sessionActive) {
      try {
        recognition.start();
      } catch (e) {
        console.warn("[STT] Could not restart recognition:", e.message);
      }
    }
  };
  
  try {
    recognition.start();
  } catch (e) {
    console.error("[STT] Failed to start recognition:", e);
    renderLogEvent({ event: "error", detail: { message: `Failed to start STT: ${e.message}` } });
  }
}

// -----------------------------------------------------------------------
// CONTROL BUTTON CLICK HANDLERS
// -----------------------------------------------------------------------
if (muteBtn) muteBtn.addEventListener("click", async () => {
  if (room && room.localParticipant) {
    await room.localParticipant.setMicrophoneEnabled(false);
    if (muteBtn) muteBtn.style.display = "none";
    if (unmuteBtn) unmuteBtn.style.display = "block";
    renderLogEvent({ event: "system", detail: "Microphone MUTED via control panel." });
  }
});

if (unmuteBtn) unmuteBtn.addEventListener("click", async () => {
  if (room && room.localParticipant) {
    await room.localParticipant.setMicrophoneEnabled(true);
    if (unmuteBtn) unmuteBtn.style.display = "none";
    if (muteBtn) muteBtn.style.display = "block";
    renderLogEvent({ event: "system", detail: "Microphone UNMUTED via control panel." });
  }
});

if (sttToggleBtn) sttToggleBtn.addEventListener("click", () => {
  sttEnabled = false;
  if (recognition) {
    try {
      recognition.stop();
    } catch (e) {}
  }
  if (sttToggleBtn) sttToggleBtn.style.display = "none";
  if (sttStartBtn) sttStartBtn.style.display = "block";
  renderLogEvent({ event: "system", detail: "Speech Recognition (STT) STOPPED/DISABLED." });
});

if (sttStartBtn) sttStartBtn.addEventListener("click", () => {
  sttEnabled = true;
  if (recognition && sessionActive) {
    try {
      recognition.start();
    } catch (e) {}
  }
  if (sttStartBtn) sttStartBtn.style.display = "none";
  if (sttToggleBtn) sttToggleBtn.style.display = "block";
  renderLogEvent({ event: "system", detail: "Speech Recognition (STT) STARTED/ENABLED." });
});

if (cancelBtn) cancelBtn.addEventListener("click", async () => {
  if (cancelBtn.disabled) return;
  cancelBtn.disabled = true;
  const originalText = cancelBtn.textContent;
  cancelBtn.textContent = "⏳ Cancelling...";
  cancelBtn.style.opacity = "0.6";
  
  stopAllQueuedAudio();
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  if (streamSocket && streamSocket.readyState === WebSocket.OPEN) {
    streamSocket.send(JSON.stringify({
      type: "cancel",
      session_id: sessionId,
      reason: "stop_button"
    }));
  }
  renderLogEvent({ event: "system", detail: "Cancelling current response..." });
  try {
    await fetch(`http://${window.location.hostname || "localhost"}:${API_PORT}/control/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, reason: "stop_button" })
    });
    updateUIState("connected", "Listening...");
    renderLogEvent({ event: "system", detail: "Response canceled successfully." });
  } catch (e) {
    console.error("[Cancel] Cancel response failed:", e);
    renderLogEvent({ event: "error", detail: { message: `Cancel failed: ${e.message}` } });
    updateUIState("connected", "Listening...");
  } finally {
    cancelBtn.disabled = false;
    cancelBtn.textContent = originalText;
    cancelBtn.style.opacity = "1";
  }
});

if (resetBtn) resetBtn.addEventListener("click", async () => {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  renderLogEvent({ event: "system", detail: "Resetting session history memory..." });
  try {
    await fetch(`http://${window.location.hostname || "localhost"}:${API_PORT}/control/reset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId })
    });
    if (userTranscriptDiv) userTranscriptDiv.textContent = "Listening for your speech...";
    if (agentResponseDiv) agentResponseDiv.textContent = "Waiting for query...";
    updateUIState("connected", "Listening...");
    renderLogEvent({ event: "system", detail: "Session memory reset successfully." });
  } catch (e) {
    console.error("[Reset] Reset session failed:", e);
  }
});

if (reconnectBtn) reconnectBtn.addEventListener("click", async () => {
  renderLogEvent({ event: "system", detail: "Reconnecting session..." });
  sessionActive = false;
  if (room) {
    try {
      await room.disconnect();
    } catch (e) {}
  }
  joinBtn.disabled = false;
  joinBtn.querySelector("span").textContent = "Join Session";
  joinBtn.classList.remove("connected");
  updateUIState("disconnected", "Disconnected");
  setTimeout(() => joinBtn.click(), 500);
});

if (shutdownBtn) shutdownBtn.addEventListener("click", async () => {
  if (confirm("Are you sure you want to shut down the API Gateway?")) {
    renderLogEvent({ event: "system", detail: "Sending API Gateway shutdown request..." });
    try {
      await fetch(`http://${window.location.hostname || "localhost"}:${API_PORT}/control/shutdown`, { method: "POST" });
    } catch (e) {}
    alert("Shutdown request sent. API Gateway process stopped.");
  }
});

// -----------------------------------------------------------------------
// WEBSOCKET & WEB AUDIO CHUNK STREAMING SYSTEM
// -----------------------------------------------------------------------
let streamSocket = null;
let audioContext = null;
let audioStartTime = 0;
let activeSources = [];
let leftoverBytes = null;
let playbackGeneration = 0; // Epoch counter — incremented on every cancellation to invalidate in-flight decodes
let currentServerTurnId = 0; // Server turn_id of the most-recently active turn — used to validate tagged binary frames

function connectWebSocketStream() {
  const wsUrl = `ws://${window.location.hostname || "localhost"}:${API_PORT}/stream`;
  console.log("[WS] Connecting to WebSocket streaming pipeline:", wsUrl);
  renderLogEvent({ event: "ws_connecting", detail: { url: wsUrl } });
  streamSocket = new WebSocket(wsUrl);
  
  streamSocket.onopen = () => {
    console.log("[WS] WebSocket streaming pipeline connected");
    const badge = document.getElementById("streaming-badge");
    if (badge) {
      badge.textContent = "Pipeline: WEBSOCKET STREAMING 🟢";
      badge.style.color = "#10b981";
    }
    renderLogEvent({ event: "ws_connected", detail: { url: wsUrl } });
    
    // Initialize Web Audio Context for gapless chunk scheduling
    // Must resume it since it may be suspended (autoplay policy)
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!audioContext) {
      audioContext = new AudioCtx();
    }
    if (audioContext.state === "suspended") {
      audioContext.resume().then(() => {
        console.log("[Audio] AudioContext resumed after user gesture");
      });
    }
    audioStartTime = audioContext.currentTime;
  };
  
  streamSocket.onmessage = async (event) => {
    if (typeof event.data === "string") {
      const msg = JSON.parse(event.data);
      console.log("[WS] Received string message:", msg.type);
      if (msg.type === "stop_audio") {
        // Advance the expected server turn_id so any frames still in-flight
        // for the cancelled turn are discarded at the binary validation step.
        if (msg.turn_id !== undefined) {
          currentServerTurnId = msg.turn_id;
        }
        stopAllQueuedAudio();
      } else if (msg.type === "llm_response") {
        // Sync the expected server turn_id once the LLM response arrives.
        if (msg.turn_id !== undefined) {
          currentServerTurnId = msg.turn_id;
        }
        console.log("[WS] LLM response received:", msg.text);
        renderLogEvent({ event: "llm_response", detail: { text: msg.text } });
        if (agentResponseDiv) {
          agentResponseDiv.textContent = msg.text;
          agentResponseDiv.classList.remove("empty");
        }
        
        // Update LLM Response Card metadata
        const modelEl = document.getElementById("llm-model");
        const tokensEl = document.getElementById("llm-tokens");
        const latencyEl = document.getElementById("llm-latency");
        if (modelEl) modelEl.textContent = VOICE_CONFIG.llm_model || "llama-3.3-70b-versatile";
        if (tokensEl) tokensEl.textContent = msg.tokens || "-";
        if (latencyEl) latencyEl.textContent = (msg.latency_ms ? msg.latency_ms + "ms" : "-");
        
        console.log("[WS] Updated Agent Response Panel with LLM response");
        renderLogEvent({ event: "agent_panel_updated", detail: { text: msg.text.slice(0, 60) } });
      } else if (msg.type === "error") {
        renderLogEvent({ event: "error", detail: { message: `Pipeline error: ${msg.detail}` } });
      }
    } else {
      // Binary audio chunk — first 4 bytes are a little-endian uint32 turn_id tag
      // written by PlaybackWorker before sending the frame.  Strip the tag,
      // validate against currentServerTurnId, and discard stale frames.
      const arrayBuffer = await event.data.arrayBuffer();
      if (arrayBuffer.byteLength < 4) return; // malformed / too short
      const tagView = new DataView(arrayBuffer, 0, 4);
      const serverTurnId = tagView.getUint32(0, /*littleEndian=*/true);
      if (serverTurnId < currentServerTurnId) {
        console.log("[WS] Discarding stale audio frame for turn", serverTurnId,
                    "(current:", currentServerTurnId, ")");
        return;
      }
      const pcmBuffer = arrayBuffer.slice(4); // strip the 4-byte tag
      if (pcmBuffer.byteLength === 0) return; // terminal sentinel (empty payload), no audio
      console.log("[WS] Received audio chunk, size:", pcmBuffer.byteLength, "turn:", serverTurnId);
      renderLogEvent({ event: "audio_chunk_received", detail: { size: pcmBuffer.byteLength } });
      decodeAndScheduleChunk(pcmBuffer);
    }
  };
  
  streamSocket.onerror = (e) => {
    console.error("[WS] WebSocket stream error:", e);
    renderLogEvent({ event: "error", detail: { message: "WebSocket stream error. Falling back to REST." } });
  };
  
  streamSocket.onclose = (e) => {
    console.log("[WS] WebSocket stream closed:", e.code, e.reason);
    const badge = document.getElementById("streaming-badge");
    if (badge) {
      badge.textContent = "Pipeline: REST";
      badge.style.color = "#a3a3a3";
    }
    renderLogEvent({ event: "ws_disconnected", detail: { code: e.code, reason: e.reason || "connection closed" } });
    streamSocket = null;
  };
}

async function decodeAndScheduleChunk(arrayBuffer) {
  if (!audioContext) {
    console.warn("[Audio] No AudioContext available, skipping chunk");
    return;
  }
  // Capture generation epoch before any async yield point
  const myGeneration = playbackGeneration;

  // Resume if suspended (autoplay policy)
  if (audioContext.state === "suspended") {
    try {
      await audioContext.resume();
    } catch (e) {
      console.warn("[Audio] Could not resume AudioContext:", e);
    }
    // Discard chunk if cancelled while suspended
    if (playbackGeneration !== myGeneration) return;
  }
  try {
    let combinedBuffer = arrayBuffer;
    
    // Prepend leftover bytes from previous chunk if present
    if (leftoverBytes) {
      const tmp = new Uint8Array(leftoverBytes.length + arrayBuffer.byteLength);
      tmp.set(leftoverBytes, 0);
      tmp.set(new Uint8Array(arrayBuffer), leftoverBytes.length);
      combinedBuffer = tmp.buffer;
      leftoverBytes = null;
    }
    
    // Check if we have an odd byte length; buffer the extra byte for next chunk
    if (combinedBuffer.byteLength % 2 !== 0) {
      leftoverBytes = new Uint8Array(combinedBuffer, combinedBuffer.byteLength - 1, 1);
      combinedBuffer = combinedBuffer.slice(0, combinedBuffer.byteLength - 1);
    }
    
    if (combinedBuffer.byteLength < 4) {
      return; // Not enough bytes to decode or check format
    }
    
    let audioBuffer;
    
    // Check if the chunk has a RIFF/WAV header (first 4 bytes: 0x52, 0x49, 0x46, 0x46)
    const headerView = new Uint8Array(combinedBuffer, 0, 4);
    const isWav = headerView[0] === 0x52 && // 'R'
                  headerView[1] === 0x49 && // 'I'
                  headerView[2] === 0x46 && // 'F'
                  headerView[3] === 0x46;   // 'F'
                  
    if (isWav) {
      // Decode using native decoder (WAV format)
      audioBuffer = await audioContext.decodeAudioData(combinedBuffer);
      // Discard chunk if cancelled while decodeAudioData was executing
      if (playbackGeneration !== myGeneration) return;
    } else {
      // Manually parse raw pcm_s16le at 24000Hz (Cartesia WebSocket output format)
      const intData = new Int16Array(combinedBuffer);
      const floatData = new Float32Array(intData.length);
      for (let i = 0; i < intData.length; i++) {
        floatData[i] = intData[i] / 32768.0;
      }
      audioBuffer = audioContext.createBuffer(1, floatData.length, 24000);
      audioBuffer.copyToChannel(floatData, 0);
    }
    
    // Final generation check immediately before scheduling — guards against
    // late in-flight WebSocket chunks that arrived after cancellation
    if (playbackGeneration !== myGeneration) return;

    const source = audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioContext.destination);
    
    const now = audioContext.currentTime;
    if (audioStartTime < now) {
      audioStartTime = now;
    }
    
    source.start(audioStartTime);
    activeSources.push(source);
    
    audioStartTime += audioBuffer.duration;
    updateUIState("speaking", "Speaking...");
    
    if (window.dispatchTelemetryEvent && activeSources.length === 1) {
      window.dispatchTelemetryEvent("playback_start", {});
      renderLogEvent({ event: "playback_started", detail: { source: "websocket_chunk" } });
    }
    
    source.onended = () => {
      activeSources = activeSources.filter(s => s !== source);
      if (activeSources.length === 0) {
        console.log("[Audio] All audio chunks played");
        renderLogEvent({ event: "playback_completed", detail: { source: "websocket_chunk" } });
        updateUIState("connected", "Listening...");
        if (window.dispatchTelemetryEvent) {
          window.dispatchTelemetryEvent("playback_end", {});
        }
      }
    };
  } catch (e) {
    console.error("[Audio] Failed to decode audio chunk:", e.message);
    renderLogEvent({ event: "error", detail: { message: `Audio decode failed: ${e.message}` } });
    if (activeSources.length === 0) {
      updateUIState("connected", "Listening...");
    }
  }
}

function stopAllQueuedAudio() {
  // Increment generation epoch — invalidates all pending async decodes and
  // in-flight WebSocket chunks from the cancelled turn
  playbackGeneration++;
  activeSources.forEach(source => {
    try {
      source.stop();
    } catch (e) {}
  });
  const hadActive = activeSources.length > 0;
  activeSources = [];
  leftoverBytes = null; // Clear any pending fragmented bytes
  audioStartTime = audioContext ? audioContext.currentTime : 0;
  updateUIState("connected", "Listening...");
  if (hadActive && window.dispatchTelemetryEvent) {
    window.dispatchTelemetryEvent("cancellation", { reason: "user_stop" });
  }
}

// -----------------------------------------------------------------------
// ROOM CONNECTIONS
// -----------------------------------------------------------------------
async function fetchToken(sessionId, roomName) {
  const url = `http://${window.location.hostname || "localhost"}:${API_PORT}/auth`;
  console.log("[Auth] Requesting LiveKit token from:", url);
  updateUIState("connecting", "Retrieving Token...");
  renderLogEvent({ event: "auth_request", detail: { msg: "Requesting LiveKit token from API Gateway...", url } });
  
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        session_id: sessionId,
        room_name: roomName
      })
    });
    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`HTTP ${response.status}: ${errText}`);
    }
    const data = await response.json();
    console.log("[Auth] Token received. LLM:", data.llm_provider, "TTS:", data.tts_provider, "STT:", data.stt_provider);
    renderLogEvent({ event: "auth_success", detail: { msg: "Token successfully retrieved." } });
    renderLogEvent({ event: "system", detail: { msg: `LLM: ${data.llm_provider} (${data.llm_model}) | TTS: ${data.tts_provider} | STT: ${data.stt_provider}` } });
    
    return { token: data.token, livekitUrl: data.livekit_url };
  } catch (err) {
    console.error("[Auth] Token fetch failed:", err);
    throw new Error(`Failed to connect to API Gateway at ${url}. Ensure the gateway is running on port ${API_PORT}. Details: ${err.message}`);
  }
}

async function connectToRoom(token, livekitUrl) {
  const LK = window.LivekitClient || window.LiveKitClient || window.LiveKit || window.Livekit;
  if (!LK) {
    console.warn("[LiveKit] SDK not found — skipping WebRTC room connection");
    renderLogEvent({ event: "system", detail: { msg: "LiveKit SDK unavailable — using REST/WebSocket pipeline only." } });
    return;
  }
  
  const { Room, RoomEvent } = LK;
  
  room = new Room();
  
  room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
    if (room.localParticipant && participant.identity === room.localParticipant.identity) {
      console.log("[LiveKit] Ignored subscribing to our own track to prevent loopback/echo");
      return;
    }
    if (track.kind === "audio") {
      track.attach(audioEl);
      console.log("[LiveKit] Audio track subscribed from:", participant.identity);
      renderLogEvent({ event: "track_subscribed", detail: { track_kind: "audio", identity: participant.identity } });
    }
  });

  room.on(RoomEvent.ParticipantConnected, (participant) => {
    console.log("[LiveKit] Participant connected:", participant.identity);
    renderLogEvent({ event: "participant_connected", detail: { identity: participant.identity } });
  });

  room.on(RoomEvent.Disconnected, (reason) => {
    console.warn("[LiveKit] Room disconnected:", reason);
    renderLogEvent({ event: "room_disconnected", detail: { reason } });
  });

  const fallbackLkUrl = (VOICE_CONFIG.livekit_url) || `ws://${window.location.hostname || "localhost"}:7800`;
  const url = livekitUrl || fallbackLkUrl;
  console.log("[LiveKit] Connecting browser WebRTC to:", url);
  renderLogEvent({ event: "livekit_connecting", detail: { url } });
  
  try {
    await room.connect(url, token);
    console.log("[LiveKit] Room connected:", room.name);
    renderLogEvent({ event: "room_joined", detail: { room: room.name } });
    
    await room.localParticipant.setMicrophoneEnabled(true);
    console.log("[LiveKit] Microphone published to room");
    renderLogEvent({ event: "mic_published", detail: { room: room.name } });
  } catch (lkErr) {
    console.warn("[LiveKit] Room connection failed (non-fatal):", lkErr.message);
    renderLogEvent({ event: "livekit_error", detail: { msg: `LiveKit failed (non-fatal): ${lkErr.message}. STT/TTS still active.` } });
  }
}

// -----------------------------------------------------------------------
// JOIN BUTTON — Main Entry Point
// -----------------------------------------------------------------------
joinBtn.addEventListener("click", async () => {
  if (sessionActive) return;
  
  console.log("[Join] Join Session button clicked. Session ID:", sessionId);
  renderLogEvent({ event: "session_start", detail: { session_id: sessionId, room: roomName } });
  
  joinBtn.disabled = true;
  joinBtn.querySelector("span").textContent = "Connecting...";

  // ---- Step 1: Fetch auth token from backend (required) ----
  let connectionInfo;
  try {
    connectionInfo = await fetchToken(sessionId, roomName);
  } catch (err) {
    console.error("[Join] Auth failed:", err.message);
    renderLogEvent({ event: "error", detail: { message: err.message } });
    updateUIState("error", "Auth Failed");
    joinBtn.disabled = false;
    joinBtn.querySelector("span").textContent = "Join Session";
    return;
  }

  // ---- Step 2: Activate session — start STT + WebSocket immediately ----
  sessionActive = true;
  updateUIState("connected", "Listening...");
  joinBtn.querySelector("span").textContent = "Session Active";
  joinBtn.classList.add("connected");
  
  console.log("[Join] Session activated — starting STT and WebSocket pipeline");
  renderLogEvent({ event: "session_active", detail: { session_id: sessionId } });
  
  // Resume AudioContext for audio playback (must happen in user gesture context)
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!audioContext) {
    audioContext = new AudioCtx();
    console.log("[Audio] AudioContext created in user gesture:", audioContext.state);
  }
  if (audioContext.state === "suspended") {
    audioContext.resume().then(() => console.log("[Audio] AudioContext resumed"));
  }
  
  startSpeechRecognition();
  connectWebSocketStream();
  
  // ---- Step 3: Connect to LiveKit (optional / non-blocking) ----
  // LiveKit provides agent-side audio track and server-side VAD.
  // This runs in background — failure does NOT break STT→LLM→TTS flow.
  connectToRoom(connectionInfo.token, connectionInfo.livekitUrl)
    .catch(err => {
      console.warn("[Join] LiveKit background connect failed:", err.message);
    });
});

// Log LiveKit SDK presence at startup
const LK_LIBRARY = window.LivekitClient || window.LiveKitClient || window.LiveKit || window.Livekit;
if (LK_LIBRARY) {
  console.log("[LiveKit] Client SDK verified and loaded successfully.");
  renderLogEvent({ event: "system", detail: { msg: "LiveKit Client SDK loaded successfully." } });
} else {
  console.warn("[LiveKit] SDK not found. Falling back to REST/WebSocket pipeline only.");
  renderLogEvent({ event: "system", detail: { msg: "⚠️ LiveKit SDK not found — REST/WebSocket pipeline will be used." } });
}

// -----------------------------------------------------------------------
// TELEMETRY UPDATERS (DEVELOPER MODE PANEL)
// -----------------------------------------------------------------------
if (toggleDashboardBtn) {
  toggleDashboardBtn.addEventListener("click", () => {
    if (metricsPanel.style.display === "none" || metricsPanel.style.display === "") {
      metricsPanel.style.display = "flex";
    } else {
      metricsPanel.style.display = "none";
    }
  });
}

// Browser FPS tracker
let lastFrameTime = performance.now();
let frameCount = 0;
function updateFPS() {
  const now = performance.now();
  frameCount++;
  const fpsInterval = (VOICE_CONFIG.ui && VOICE_CONFIG.ui.fps_calc_interval_ms) || 1000;
  if (now > lastFrameTime + fpsInterval) {
    const fps = Math.round((frameCount * 1000) / (now - lastFrameTime));
    const el = document.getElementById("browser-fps");
    if (el) el.textContent = fps;
    frameCount = 0;
    lastFrameTime = now;
  }
  requestAnimationFrame(updateFPS);
}
requestAnimationFrame(updateFPS);

// Browser Event Loop Lag Tracker
let lastLoopTime = performance.now();
function checkLoopLag() {
  const now = performance.now();
  const lagInterval = (VOICE_CONFIG.ui && VOICE_CONFIG.ui.loop_lag_interval_ms) || 50;
  const lag = Math.max(0, now - lastLoopTime - lagInterval);
  const el = document.getElementById("browser-loop");
  if (el) el.textContent = lag.toFixed(1);
  lastLoopTime = now;
  setTimeout(checkLoopLag, lagInterval);
}
const initialLagInterval = (VOICE_CONFIG.ui && VOICE_CONFIG.ui.loop_lag_interval_ms) || 50;
setTimeout(checkLoopLag, initialLagInterval);

setInterval(() => {
  const domEl = document.getElementById("browser-dom");
  if (domEl) domEl.textContent = document.getElementsByTagName('*').length;
  const heapEl = document.getElementById("browser-heap");
  const mem = window.performance?.memory;
  const heap = mem ? (mem.usedJSHeapSize / (1024 * 1024)).toFixed(1) : "-";
  if (heapEl) heapEl.textContent = heap;
}, (VOICE_CONFIG.ui && VOICE_CONFIG.ui.dom_heap_interval_ms) || 1000);

// WebRTC peer connection stats
async function updateWebRTCStats() {
  if (!room || room.state !== "connected") return;
  const pc = room.engine?.client?.peerConnection;
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
}
setInterval(updateWebRTCStats, (VOICE_CONFIG.ui && VOICE_CONFIG.ui.webrtc_stats_interval_ms) || 2000);

// Helper function to update a latency table row
function updateRow(rowId, stats, targetMs) {
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
  
  // Set threshold colors
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
}

// Mark health services as failed after first poll attempt failure
let healthPollAttempted = false;

// Backend and local telemetry polling loop
async function pollTelemetryData() {
  const url = `http://${window.location.hostname || "localhost"}:${API_PORT}/telemetry`;
  try {
    const response = await fetch(url);
    if (!response.ok) {
      healthPollAttempted = true;
      return;
    }
    healthPollAttempted = true;
    const data = await response.json();
    
    // Server resource details — using actual IDs from dashboard HTML
    const cpuEl = document.getElementById("live-cpu");
    const ramEl = document.getElementById("live-memory");
    if (cpuEl && data.resources) cpuEl.textContent = `${data.resources.cpu}%`;
    if (ramEl && data.resources) ramEl.textContent = `${data.resources.ram} MB`;
    
    // Token usage cost meters
    const pTokEl = document.getElementById("metrics-prompt-tokens");
    const cTokEl = document.getElementById("metrics-completion-tokens");
    const costEl = document.getElementById("metrics-cost");
    const tpsEl = document.getElementById("live-tokens-sec");
    if (pTokEl && data.tokens) pTokEl.textContent = data.tokens.prompt_tokens;
    if (cTokEl && data.tokens) cTokEl.textContent = data.tokens.completion_tokens;
    if (costEl && data.tokens) costEl.textContent = `$${data.tokens.cost.toFixed(4)}`;
    
    // Speed estimator
    if (data.total && data.total.curr > 0 && data.tokens && data.tokens.completion_tokens > 0) {
      const speed = (data.tokens.completion_tokens / (data.total.curr / 1000)).toFixed(1);
      if (tpsEl) tpsEl.textContent = `${speed} t/s`;
    } else {
      if (tpsEl) tpsEl.textContent = "- t/s";
    }
    
    // Service Health light states
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
    
    const thresholds = VOICE_CONFIG.latency_threshold_targets || {};
    if (data.llm) updateRow("metric-row-llm", data.llm, thresholds.llm || 800);
    if (data.tts) updateRow("metric-row-tts", data.tts, thresholds.tts || 250);
    if (data.total) updateRow("metric-row-total", data.total, thresholds.total || 1200);
    
    // Calculate and render local STT and Network statistics
    const getLocalStats = (vals) => {
      if (!vals.length) return { curr: 0 };
      return {
        curr: vals[vals.length - 1],
        avg: Math.round(vals.reduce((a, b) => a + b, 0) / vals.length),
        min: Math.min(...vals),
        max: Math.max(...vals),
        p95: calculatePercentile(vals, 95),
        p99: calculatePercentile(vals, 99)
      };
    };
    
    const localSttStats = getLocalStats(localHistory.stt);
    const localNetworkStats = getLocalStats(localHistory.network);
    const localInterruptStats = getLocalStats(localHistory.interruption);
    
    const thresh = VOICE_CONFIG.latency_threshold_targets || {};
    updateRow("metric-row-stt", localSttStats, thresh.stt || 250);
    updateRow("metric-row-network", localNetworkStats, thresh.network || 150);
    updateRow("metric-row-interruption", localInterruptStats, thresh.interruption || 100);
    
    // Realtime diagnostics report panel
    const bottleneckDiv = document.getElementById("bottleneck-info");
    if (bottleneckDiv) {
      let report = "";
      if (!data.total || data.total.curr === 0) {
        report = "No conversation data analyzed yet. Talk to the agent to start latency profiling!";
      } else {
        const slowStage = (data.llm.curr > data.tts.curr) ? "LLM (Groq)" : "TTS (Cartesia)";
        const slowLat = Math.max(data.llm.curr, data.tts.curr);
        report = `Slowest Stage: ${slowStage} (${slowLat}ms)<br/>`;
        
        const totalTarget = (VOICE_CONFIG.latency_threshold_targets || {}).total || 1200;
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
      replaceCheckingStatus();
    }
    // Only warn once — don't spam when services aren't up yet
  }
}

function replaceCheckingStatus() {
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
}

const pollInterval = VOICE_CONFIG.telemetry_refresh_rate_ms || 2000;
setInterval(pollTelemetryData, pollInterval);
