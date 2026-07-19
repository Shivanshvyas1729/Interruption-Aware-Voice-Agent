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
  } catch (_) { /* use defaults */ }
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
    waveContainer.classList.add("animating");
    document.querySelectorAll(".wave-bar").forEach(bar => {
      bar.style.backgroundColor = color;
    });
  } else {
    waveContainer.classList.remove("animating");
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

// ----------------------------------------------------------------------------
// MICROPHONE LEVEL ANALYSER (WEB AUDIO API)
// ----------------------------------------------------------------------------
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
    console.warn("Could not start Web Audio analyser for mic energy:", e);
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
navigator.mediaDevices.getUserMedia({ audio: true })
  .then(stream => {
    micStream = stream;
    startMicEnergyTracker(stream);
  })
  .catch(err => {
    console.warn("Microphone analysis initialization bypassed:", err);
  });

// ----------------------------------------------------------------------------
// AUDIO PLAYBACK GATES
// ----------------------------------------------------------------------------
function playBase64Audio(base64Data) {
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
      updateUIState("speaking", "Speaking...");
      
      if (window.dispatchTelemetryEvent) {
        window.dispatchTelemetryEvent("playback_start", {});
      }
      
      // Mark playback start in waterfall
      if (speechStartTime > 0) {
        const playbackStart = Math.round(performance.now() - speechStartTime);
        document.getElementById("wf-playback-start").textContent = `+${playbackStart}ms`;
      }
    };
    
    currentAudio.onended = () => {
      updateUIState("connected", "Listening...");
      currentAudio = null;
      if (window.dispatchTelemetryEvent) {
        window.dispatchTelemetryEvent("playback_end", {});
      }
    };
    
    currentAudio.play().catch(err => {
      console.error("Audio playback error:", err);
      renderLogEvent({ event: "error", detail: { message: `Audio playback failed: ${err.message}` } });
      updateUIState("connected", "Listening...");
    });
  } catch (e) {
    console.error("Failed to decode base64 audio:", e);
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
    console.error("Failed to notify gateway of barge-in:", e);
  }
}

// ----------------------------------------------------------------------------
// SPEECH RECOGNITION (STT) GATEWAYS
// ----------------------------------------------------------------------------
function startSpeechRecognition() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    renderLogEvent({ event: "error", detail: { message: "SpeechRecognition is not supported in this browser. Please use Chrome or Edge." } });
    return;
  }
  
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = false;
  recognition.lang = VOICE_CONFIG.stt_language || 'en-US';
  
  recognition.onstart = () => {
    renderLogEvent({ event: "system", detail: { msg: "Speech recognition worker started. Speak into your mic!" } });
    updateUIState("connected", "Listening...");
  };
  
  recognition.onspeechstart = () => {
    const interruptStart = performance.now();
    speechStartTime = performance.now();
    
    // Clear waterfall view for new turn safely
    const ids = ["wf-vad-start", "wf-stt-complete", "wf-llm-first-token", "wf-llm-complete", "wf-tts-first-audio", "wf-playback-start", "wf-playback-end", "wf-orch-start", "wf-tts-complete"];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = "-";
    });
    
    // Dispatch telemetry event for VAD start
    if (window.dispatchTelemetryEvent) {
      window.dispatchTelemetryEvent("vad_start", {});
    }
    
    if (currentAudio) {
      console.log("Speech detected! Interrupted active audio.");
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
    
    // Update STT waterfall safely
    const elStt = document.getElementById("wf-stt-complete");
    if (elStt) elStt.textContent = `+${sttLatency}ms`;
    
    userTranscriptDiv.textContent = transcript;
    renderLogEvent({ event: "stt_final", detail: { text: transcript } });
    
    updateUIState("thinking", "Thinking...");
    
    const startFetch = performance.now();
    if (speechStartTime === 0) speechStartTime = startFetch;
    timeOrchStart = Math.round(startFetch - speechStartTime);
    const elOrch = document.getElementById("wf-orch-start") || document.getElementById("wf-vad-start");
    if (elOrch) elOrch.textContent = `+${timeOrchStart}ms`;
    
    if (streamSocket && streamSocket.readyState === WebSocket.OPEN) {
      streamSocket.send(JSON.stringify({
        type: "transcript",
        session_id: sessionId,
        text: transcript
      }));
      return;
    }
    
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
        throw new Error(`HTTP error! Status: ${response.status}`);
      }
      const data = await response.json();
      const endFetch = performance.now();
      
      const totalFetchDuration = Math.round(endFetch - startFetch);
      const backendDuration = data.total_latency || 0;
      const networkRTT = Math.max(5, totalFetchDuration - backendDuration);
      localHistory.network.push(networkRTT);
      
      // Update LLM/TTS waterfall timestamps using backend-latency fields
      const llmLate = data.llm_latency || 0;
      const ttsLate = data.tts_latency || 0;
      const totalLate = data.total_latency || 0;
      const llmFinish = timeOrchStart + llmLate;
      const ttsFinish = timeOrchStart + llmLate + ttsLate;
      // Update LLM/TTS waterfall safely
      const elLlm = document.getElementById("wf-llm-complete");
      if (elLlm) elLlm.textContent = `+${llmFinish}ms`;
      const elTts = document.getElementById("wf-tts-complete") || document.getElementById("wf-tts-first-audio");
      if (elTts) elTts.textContent = `+${ttsFinish}ms`;
      
      agentResponseDiv.textContent = data.reply;
      renderLogEvent({ event: "llm_response", detail: { text: data.reply } });
      
      if (data.audio) {
        playBase64Audio(data.audio);
      } else {
        updateUIState("connected", "Listening...");
      }
    } catch (err) {
      console.error("Turn fetch failed:", err);
      renderLogEvent({ event: "error", detail: { message: `Voice processing failed: ${err.message}` } });
      updateUIState("connected", "Listening...");
    }
  };
  
  recognition.onerror = (e) => {
    if (e.error !== 'no-speech') {
      renderLogEvent({ event: "error", detail: { message: `Speech recognition error: ${e.error}` } });
    }
  };
  
  recognition.onend = () => {
    if (sttEnabled && room && room.state === "connected") {
      recognition.start();
    }
  };
  
  recognition.start();
}

// ----------------------------------------------------------------------------
// CONTROL BUTTON CLICK HANDLERS
// ----------------------------------------------------------------------------
muteBtn.addEventListener("click", async () => {
  if (room && room.localParticipant) {
    await room.localParticipant.setMicrophoneEnabled(false);
    muteBtn.style.display = "none";
    unmuteBtn.style.display = "block";
    renderLogEvent({ event: "system", detail: "Microphone MUTED via control panel." });
  }
});

unmuteBtn.addEventListener("click", async () => {
  if (room && room.localParticipant) {
    await room.localParticipant.setMicrophoneEnabled(true);
    unmuteBtn.style.display = "none";
    muteBtn.style.display = "block";
    renderLogEvent({ event: "system", detail: "Microphone UNMUTED via control panel." });
  }
});

sttToggleBtn.addEventListener("click", () => {
  sttEnabled = false;
  if (recognition) {
    try {
      recognition.stop();
    } catch (e) {}
  }
  sttToggleBtn.style.display = "none";
  sttStartBtn.style.display = "block";
  renderLogEvent({ event: "system", detail: "Speech Recognition (STT) STOPPED/DISABLED." });
});

sttStartBtn.addEventListener("click", () => {
  sttEnabled = true;
  if (recognition && room && room.state === "connected") {
    try {
      recognition.start();
    } catch (e) {}
  }
  sttStartBtn.style.display = "none";
  sttToggleBtn.style.display = "block";
  renderLogEvent({ event: "system", detail: "Speech Recognition (STT) STARTED/ENABLED." });
});

cancelBtn.addEventListener("click", async () => {
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
    console.error("Cancel response failed:", e);
    renderLogEvent({ event: "error", detail: { message: `Cancel failed: ${e.message}` } });
    updateUIState("connected", "Listening...");
  } finally {
    cancelBtn.disabled = false;
    cancelBtn.textContent = originalText;
    cancelBtn.style.opacity = "1";
  }
});

resetBtn.addEventListener("click", async () => {
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
    userTranscriptDiv.textContent = "Listening for your speech...";
    agentResponseDiv.textContent = "Waiting for query...";
    updateUIState("connected", "Listening...");
    renderLogEvent({ event: "system", detail: "Session memory reset successfully." });
  } catch (e) {
    console.error("Reset session failed:", e);
  }
});

reconnectBtn.addEventListener("click", async () => {
  renderLogEvent({ event: "system", detail: "Reconnecting room..." });
  if (room) {
    try {
      await room.disconnect();
    } catch (e) {}
  }
  joinBtn.disabled = false;
  joinBtn.textContent = "Join Session";
  joinBtn.classList.remove("connected");
  updateUIState("disconnected", "Disconnected");
  joinBtn.click();
});

shutdownBtn.addEventListener("click", async () => {
  if (confirm("Are you sure you want to shut down the API Gateway?")) {
    renderLogEvent({ event: "system", detail: "Sending API Gateway shutdown request..." });
    try {
      await fetch(`http://${window.location.hostname || "localhost"}:${API_PORT}/control/shutdown`, { method: "POST" });
    } catch (e) {}
    alert("Shutdown request sent. API Gateway process stopped.");
  }
});

// ----------------------------------------------------------------------------
// WEBSOCKET & WEB AUDIO CHUNK STREAMING SYSTEM
// ----------------------------------------------------------------------------
let streamSocket = null;
let audioContext = null;
let audioStartTime = 0;
let activeSources = [];

function connectWebSocketStream() {
  const wsUrl = `ws://${window.location.hostname || "localhost"}:${API_PORT}/stream`;
  renderLogEvent({ event: "system", detail: "Connecting to WebSocket streaming pipeline..." });
  streamSocket = new WebSocket(wsUrl);
  
  streamSocket.onopen = () => {
    const badge = document.getElementById("streaming-badge");
    if (badge) {
      badge.textContent = "Pipeline: WEBSOCKET STREAMING 🟢";
      badge.style.color = "#10b981";
    }
    renderLogEvent({ event: "system", detail: "WebSocket streaming pipeline connected." });
    
    // Initialize Web Audio Context for gapless chunk scheduling
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioCtx();
    audioStartTime = audioContext.currentTime;
  };
  
  streamSocket.onmessage = async (event) => {
    if (typeof event.data === "string") {
      const msg = JSON.parse(event.data);
      if (msg.type === "stop_audio") {
        stopAllQueuedAudio();
      }
    } else {
      const arrayBuffer = await event.data.arrayBuffer();
      decodeAndScheduleChunk(arrayBuffer);
    }
  };
  
  streamSocket.onerror = (e) => {
    console.error("WebSocket stream error:", e);
  };
  
  streamSocket.onclose = () => {
    const badge = document.getElementById("streaming-badge");
    if (badge) {
      badge.textContent = "Pipeline: REST";
      badge.style.color = "#a3a3a3";
    }
    renderLogEvent({ event: "system", detail: "WebSocket streaming pipeline disconnected. Falling back to REST." });
  };
}

async function decodeAndScheduleChunk(arrayBuffer) {
  if (!audioContext) return;
  try {
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
    
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
    }
    
    source.onended = () => {
      activeSources = activeSources.filter(s => s !== source);
      if (activeSources.length === 0) {
        updateUIState("connected", "Listening...");
        if (window.dispatchTelemetryEvent) {
          window.dispatchTelemetryEvent("playback_end", {});
        }
      }
    };
  } catch (e) {
    console.warn("Failed to decode audio chunk:", e);
    if (activeSources.length === 0) {
      updateUIState("connected", "Listening...");
    }
  }
}

function stopAllQueuedAudio() {
  activeSources.forEach(source => {
    try {
      source.stop();
    } catch (e) {}
  });
  const hadActive = activeSources.length > 0;
  activeSources = [];
  audioStartTime = audioContext ? audioContext.currentTime : 0;
  updateUIState("connected", "Listening...");
  if (hadActive && window.dispatchTelemetryEvent) {
    window.dispatchTelemetryEvent("cancellation", { reason: "user_stop" });
  }
}

// ----------------------------------------------------------------------------
// ROOM CONNECTIONS
// ----------------------------------------------------------------------------
async function fetchToken(sessionId, roomName) {
  const url = `http://${window.location.hostname || "localhost"}:${API_PORT}/auth`;
  updateUIState("connecting", "Retrieving Token...");
  renderLogEvent({ event: "system", detail: { msg: "Requesting LiveKit token from API Gateway...", url } });
  
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
      throw new Error(`HTTP error! Status: ${response.status}`);
    }
    const data = await response.json();
    renderLogEvent({ event: "system", detail: { msg: "Token successfully retrieved from API Gateway." } });
    
    renderLogEvent({ event: "system", detail: { msg: `LLM Provider Loaded: ${data.llm_provider} (Model: ${data.llm_model})` } });
    renderLogEvent({ event: "system", detail: { msg: `TTS Provider Loaded: ${data.tts_provider}` } });
    renderLogEvent({ event: "system", detail: { msg: `STT Provider Loaded: ${data.stt_provider}` } });
    
    return { token: data.token, livekitUrl: data.livekit_url };
  } catch (err) {
    console.error("Token fetch failed:", err);
    throw new Error(`Failed to connect to API Gateway at ${url}. Ensure the gateway service is running on port ${API_PORT}. Details: ${err.message}`);
  }
}

async function connectToRoom(token, livekitUrl) {
  const LK = window.LivekitClient || window.LiveKitClient || window.LiveKit || window.Livekit;
  if (!LK) {
    throw new Error("LiveKit SDK not found. Verify that livekit-client.umd.min.js was loaded correctly.");
  }
  
  const { Room, RoomEvent } = LK;
  
  room = new Room();
  
  room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
    if (track.kind === "audio") {
      track.attach(audioEl);
      renderLogEvent({ event: "track_subscribed", detail: { track_kind: "audio", identity: participant.identity } });
    }
  });

  room.on(RoomEvent.ParticipantConnected, (participant) => {
    renderLogEvent({ event: "participant_connected", detail: { identity: participant.identity } });
  });

  updateUIState("connecting", "Connecting Room...");
  
  const fallbackLkUrl = (VOICE_CONFIG.livekit_url) || `ws://${window.location.hostname || "localhost"}:7800`;
  const url = livekitUrl || fallbackLkUrl;
  renderLogEvent({ event: "system", detail: { msg: `Connecting browser WebRTC to LiveKit server at ${url}...` } });
  
  await room.connect(url, token);
  
  updateUIState("connected", "Listening...");
  joinBtn.textContent = "Session Active";
  joinBtn.classList.add("connected");
  joinBtn.disabled = true;
  
  renderLogEvent({ event: "room_joined", detail: { room: room.name } });

  await room.localParticipant.setMicrophoneEnabled(true);
  renderLogEvent({ event: "track_published", detail: { track_kind: "audio" } });
  
  startSpeechRecognition();
  connectWebSocketStream();
}

joinBtn.addEventListener("click", async () => {
  try {
    const connectionInfo = await fetchToken(sessionId, roomName);
    await connectToRoom(connectionInfo.token, connectionInfo.livekitUrl);
  } catch (err) {
    renderLogEvent({ event: "error", detail: { message: err.message } });
    updateUIState("error", "Connection Failed");
  }
});

const LK_LIBRARY = window.LivekitClient || window.LiveKitClient || window.LiveKit || window.Livekit;
if (LK_LIBRARY) {
  renderLogEvent({ event: "system", detail: { msg: "LiveKit Client SDK verified and loaded successfully." } });
} else {
  renderLogEvent({ event: "error", detail: { message: "LiveKit SDK not found. Make sure livekit-client.umd.min.js exists." } });
}

// ----------------------------------------------------------------------------
// TELEMETRY UPDATERS (DEVELOPER MODE PANEL)
// ----------------------------------------------------------------------------
toggleDashboardBtn.addEventListener("click", () => {
  if (metricsPanel.style.display === "none") {
    metricsPanel.style.display = "flex";
  } else {
    metricsPanel.style.display = "none";
  }
});

// Browser FPS tracker
let lastFrameTime = performance.now();
let frameCount = 0;
function updateFPS() {
  const now = performance.now();
  frameCount++;
  const fpsInterval = (VOICE_CONFIG.ui && VOICE_CONFIG.ui.fps_calc_interval_ms) || 1000;
  if (now > lastFrameTime + fpsInterval) {
    const fps = Math.round((frameCount * 1000) / (now - lastFrameTime));
    document.getElementById("browser-fps").textContent = fps;
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
  document.getElementById("browser-loop").textContent = lag.toFixed(1);
  lastLoopTime = now;
  setTimeout(checkLoopLag, lagInterval);
}
const initialLagInterval = (VOICE_CONFIG.ui && VOICE_CONFIG.ui.loop_lag_interval_ms) || 50;
setTimeout(checkLoopLag, initialLagInterval);

setInterval(() => {
  document.getElementById("browser-dom").textContent = document.getElementsByTagName('*').length;
  const mem = window.performance?.memory;
  const heap = mem ? (mem.usedJSHeapSize / (1024 * 1024)).toFixed(1) : "-";
  document.getElementById("browser-heap").textContent = heap;
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
    document.getElementById("webrtc-jitter").textContent = jitter;
    document.getElementById("webrtc-loss").textContent = packetsLost;
    document.getElementById("webrtc-bitrate").textContent = bitrate;
  } catch (e) {
    console.warn("Failed fetching WebRTC connection stats:", e);
  }
}
setInterval(updateWebRTCStats, (VOICE_CONFIG.ui && VOICE_CONFIG.ui.webrtc_stats_interval_ms) || 2000);

// Helper function to update a latency table row in index.html
function updateRow(rowId, stats, targetMs) {
  const row = document.getElementById(rowId);
  if (!row) return;
  
  const currCell = row.querySelector(".val-curr");
  const avgCell = row.querySelector(".val-avg");
  const minmaxCell = row.querySelector(".val-minmax");
  const p95p99Cell = row.querySelector(".val-p95p99");
  const statusCell = row.querySelector(".val-status");
  
  if (stats.curr === 0) {
    currCell.textContent = "-";
    avgCell.textContent = "-";
    minmaxCell.textContent = "-";
    p95p99Cell.textContent = "-";
    statusCell.textContent = "-";
    return;
  }
  
  currCell.textContent = `${stats.curr}ms`;
  avgCell.textContent = `${stats.avg}ms`;
  minmaxCell.textContent = `${stats.min}ms / ${stats.max}ms`;
  p95p99Cell.textContent = `${stats.p95}ms / ${stats.p99}ms`;
  
  // Set thresholds colors
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
    
    // Server resource details
    document.getElementById("server-cpu").textContent = data.resources.cpu;
    document.getElementById("server-ram").textContent = data.resources.ram;
    document.getElementById("server-threads").textContent = data.resources.threads;
    document.getElementById("server-tasks").textContent = data.resources.async_tasks;
    document.getElementById("server-session").textContent = sessionId;
    
    // Token usage cost meters
    document.getElementById("metrics-prompt-tokens").textContent = data.tokens.prompt_tokens;
    document.getElementById("metrics-completion-tokens").textContent = data.tokens.completion_tokens;
    document.getElementById("metrics-cost").textContent = `$${data.tokens.cost.toFixed(4)}`;
    
    // Speed estimator
    if (data.total.curr > 0 && data.tokens.completion_tokens > 0) {
      const speed = (data.tokens.completion_tokens / (data.total.curr / 1000)).toFixed(1);
      document.getElementById("metrics-tokens-sec").textContent = `${speed} t/s`;
    } else {
      document.getElementById("metrics-tokens-sec").textContent = "- t/s";
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
    
    updateService("api", data.services.api_gateway);
    updateService("redis", data.services.redis);
    updateService("orch", data.services.orchestrator);
    updateService("media", data.services.media_gateway);
    
    const thresholds = VOICE_CONFIG.latency_threshold_targets || {};
    updateRow("metric-row-llm", data.llm, thresholds.llm || 800);
    updateRow("metric-row-tts", data.tts, thresholds.tts || 250);
    updateRow("metric-row-total", data.total, thresholds.total || 1200);
    
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
    let report = "";
    if (data.total.curr === 0) {
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
    
  } catch (err) {
    if (!healthPollAttempted) {
      healthPollAttempted = true;
      replaceCheckingStatus();
    }
    console.warn("Telemetry polling failed:", err);
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
