// ---------------------------------------------------------------------------
// Global Shared State for modularized voice agent scripts
// ---------------------------------------------------------------------------

window.VOICE_CONFIG = {};
window.API_PORT = 8003;
window.CFG_URL = `http://${window.location.hostname || "localhost"}:${window.API_PORT}/config`;

// Session trackers
window.sessionId = "session-" + Math.random().toString(36).substring(2, 9);
window.roomName = "demo-room";
window.room = null;
window.recognition = null;
window.currentAudio = null;
window.sessionActive = false;

// Latency & Telemetry trackers
window.speechStartTime = 0;
window.timeSTTComplete = 0;
window.timeOrchStart = 0;
window.localHistory = {
  stt: [],
  network: [],
  interruption: []
};

// Web Audio resources
window.audioContextForMic = null;
window.analyserNode = null;
window.micStream = null;
window.micEnergyInterval = null;

// UI color status mapping
window.statusColors = {
  disconnected: "#3b82f6",
  connecting: "#f59e0b",
  connected: "#10b981",
  error: "#ef4444",
  speaking: "#ec4899",
  thinking: "#a855f7"
};
window.stateTimeoutId = null;

// Streaming Audio resources
window.streamSocket = null;
window.audioContext = null;
window.audioStartTime = 0;
window.activeSources = [];
window.leftoverBytes = null;
window.playbackGeneration = 0;
window.currentServerTurnId = 0;
window.awaitingNewTurn = false;

// Dashboard telemetry resources
window.pipelineEls = {
  vad: document.getElementById("pipeline-vad"),
  stt: document.getElementById("pipeline-stt"),
  llm: document.getElementById("pipeline-llm"),
  tts: document.getElementById("pipeline-tts"),
  playback: document.getElementById("pipeline-playback")
};
window.telemetryFeed = document.getElementById("telemetry-feed");
window.turnStartTs = 0;
window.sessionMetrics = {
  sttCount: 0,
  llmCount: 0,
  ttsCount: 0,
  turnCount: 0,
  totalTokens: 0,
  totalCost: 0,
  maxQueueLen: 0
};
