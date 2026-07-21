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
window._ttsFirstAudioFired = false;
window._playbackStartFired = false;
window._turnRecorded = false;
window.currentTurnIndex = 0;
window.lastRecordedTurnId = -1;
window._turnInProgress = false;

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
window.formatIST = function(d) {
  const date = d ? (d instanceof Date ? d : new Date(d)) : new Date();
  return date.toLocaleString("en-US", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    second: "numeric",
    hour12: true
  }) + " (IST)";
};

window.sessionMetricsHistory = {
  session_id: window.sessionId,
  start_time: window.formatIST(),
  system_snapshots: [],
  turn_latency_records: [],
  high_latency_warnings: []
};
