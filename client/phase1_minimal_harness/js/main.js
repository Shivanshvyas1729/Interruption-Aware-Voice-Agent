// ---------------------------------------------------------------------------
// Main Coordinator - initializes modules, manages core click handlers, and
// starts performance loops (FPS, loop lag).
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  // 1. Initial config loading and settings sync
  await window.loadVoiceConfig();
  await window.fetchSettings();

  // 2. Main sidebar action buttons & listeners
  const joinBtn = document.getElementById("join-btn");
  const cancelBtn = document.getElementById("ctrl-cancel-btn");
  const resetBtn = document.getElementById("ctrl-reset-btn");
  const reconnectBtn = document.getElementById("ctrl-reconnect-btn");
  const shutdownBtn = document.getElementById("ctrl-shutdown-btn");
  const sttToggleBtn = document.getElementById("ctrl-stt-toggle-btn");
  const sttStartBtn = document.getElementById("ctrl-stt-start-btn");

  const muteBtn = document.getElementById("ctrl-mute-btn");
  const unmuteBtn = document.getElementById("ctrl-unmute-btn");

  if (joinBtn) {
    joinBtn.addEventListener("click", async () => {
      if (window.sessionActive) {
        window.leaveSession();
        return;
      }
      
      console.log("[Join] Join Session button clicked. Session ID:", window.sessionId);
      window.renderLogEvent({ event: "session_start", detail: { session_id: window.sessionId, room: window.roomName } });
      
      joinBtn.disabled = true;
      joinBtn.querySelector("span").textContent = "Connecting...";

      let connectionInfo;
      try {
        connectionInfo = await window.fetchToken(window.sessionId, window.roomName);
      } catch (err) {
        console.error("[Join] Auth failed:", err.message);
        window.renderLogEvent({ event: "error", detail: { message: err.message } });
        window.updateUIState("error", "Auth Failed");
        joinBtn.disabled = false;
        joinBtn.querySelector("span").textContent = "Join Session";
        joinBtn.style.background = "linear-gradient(135deg, #3b82f6, #8b5cf6)";
        return;
      }

      window.sessionActive = true;
      window.updateUIState("connected", "Listening...");
      joinBtn.disabled = false;
      joinBtn.querySelector("span").textContent = "Leave Session";
      joinBtn.style.background = "linear-gradient(135deg, #ef4444, #dc2626)";
      
      console.log("[Join] Session activated — starting STT and WebSocket pipeline");
      window.renderLogEvent({ event: "session_active", detail: { session_id: window.sessionId } });
      
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!window.audioContext) {
        window.audioContext = new AudioCtx();
        console.log("[Audio] AudioContext created in user gesture:", window.audioContext.state);
      }
      if (window.audioContext.state === "suspended") {
        window.audioContext.resume().then(() => console.log("[Audio] AudioContext resumed"));
      }
      
      window.startSpeechRecognition();
      window.connectWebSocketStream();
      
      window.connectToRoom(connectionInfo.token, connectionInfo.livekitUrl)
        .catch(err => {
          console.warn("[Join] LiveKit background connect failed:", err.message);
        });
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async () => {
      if (cancelBtn.disabled) return;
      cancelBtn.disabled = true;
      const originalText = cancelBtn.textContent;
      cancelBtn.textContent = "⏳ Cancelling...";
      cancelBtn.style.opacity = "0.6";
      
      window.stopAllQueuedAudio();
      if (window.currentAudio) {
        window.currentAudio.pause();
        window.currentAudio = null;
      }
      if (window.streamSocket && window.streamSocket.readyState === WebSocket.OPEN) {
        window.streamSocket.send(JSON.stringify({
          type: "cancel",
          session_id: window.sessionId,
          reason: "stop_button"
        }));
      }
      window.renderLogEvent({ event: "system", detail: "Cancelling current response..." });
      try {
        await fetch(`http://${window.location.hostname || "localhost"}:${window.API_PORT}/control/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: window.sessionId, reason: "stop_button" })
        });
        window.updateUIState("connected", "Listening...");
        window.renderLogEvent({ event: "system", detail: "Response canceled successfully." });
      } catch (e) {
        console.error("[Cancel] Cancel response failed:", e);
        window.renderLogEvent({ event: "error", detail: { message: `Cancel failed: ${e.message}` } });
        window.updateUIState("connected", "Listening...");
      } finally {
        cancelBtn.disabled = false;
        cancelBtn.textContent = originalText;
        cancelBtn.style.opacity = "1";
      }
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      window.stopAllQueuedAudio();
      if (window.currentAudio) {
        window.currentAudio.pause();
        window.currentAudio = null;
      }
      window.renderLogEvent({ event: "system", detail: "Resetting session history memory..." });
      try {
        await fetch(`http://${window.location.hostname || "localhost"}:${window.API_PORT}/control/reset`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: window.sessionId })
        });
        const userTranscriptDiv = document.getElementById("user-transcript");
        const agentResponseDiv = document.getElementById("agent-response");
        if (userTranscriptDiv) userTranscriptDiv.textContent = "Listening for your speech...";
        if (agentResponseDiv) agentResponseDiv.textContent = "Waiting for query...";
        window.updateUIState("connected", "Listening...");
        window.renderLogEvent({ event: "system", detail: "Session memory reset successfully." });
      } catch (e) {
        console.error("[Reset] Reset session failed:", e);
      }
    });
  }

  if (reconnectBtn) {
    reconnectBtn.addEventListener("click", async () => {
      window.renderLogEvent({ event: "system", detail: "Reconnecting session..." });
      window.sessionActive = false;
      if (window.room) {
        try {
          await window.room.disconnect();
        } catch (e) {}
      }
      if (joinBtn) {
        joinBtn.disabled = false;
        joinBtn.querySelector("span").textContent = "Join Session";
        window.updateUIState("disconnected", "Disconnected");
        setTimeout(() => joinBtn.click(), 500);
      }
    });
  }

  if (shutdownBtn) {
    shutdownBtn.addEventListener("click", async () => {
      if (confirm("Are you sure you want to shut down the API Gateway?")) {
        window.renderLogEvent({ event: "system", detail: "Sending API Gateway shutdown request..." });
        try {
          await fetch(`http://${window.location.hostname || "localhost"}:${window.API_PORT}/control/shutdown`, { method: "POST" });
        } catch (e) {}
        alert("Shutdown request sent. API Gateway process stopped.");
      }
    });
  }

  if (sttToggleBtn) {
    sttToggleBtn.addEventListener("click", () => {
      window.sttEnabled = false;
      if (window.recognition) {
        try { window.recognition.stop(); } catch (e) {}
      }
      sttToggleBtn.style.display = "none";
      if (sttStartBtn) sttStartBtn.style.display = "block";
      window.renderLogEvent({ event: "system", detail: "Speech Recognition (STT) STOPPED/DISABLED." });
    });
  }

  if (sttStartBtn) {
    sttStartBtn.addEventListener("click", () => {
      window.sttEnabled = true;
      if (window.recognition && window.sessionActive) {
        try { window.recognition.start(); } catch (e) {}
      }
      sttStartBtn.style.display = "none";
      if (sttToggleBtn) sttToggleBtn.style.display = "block";
      window.renderLogEvent({ event: "system", detail: "Speech Recognition (STT) STARTED/ENABLED." });
    });
  }

  if (muteBtn) {
    muteBtn.addEventListener("click", async () => {
      if (window.room && window.room.localParticipant) {
        await window.room.localParticipant.setMicrophoneEnabled(false);
        muteBtn.style.display = "none";
        if (unmuteBtn) unmuteBtn.style.display = "block";
        window.renderLogEvent({ event: "system", detail: "Microphone MUTED via control panel." });
      }
    });
  }

  if (unmuteBtn) {
    unmuteBtn.addEventListener("click", async () => {
      if (window.room && window.room.localParticipant) {
        await window.room.localParticipant.setMicrophoneEnabled(true);
        unmuteBtn.style.display = "none";
        if (muteBtn) muteBtn.style.display = "block";
        window.renderLogEvent({ event: "system", detail: "Microphone UNMUTED via control panel." });
      }
    });
  }

  // Sidebar collapsible drawer triggers
  const toggleDashboardBtn = document.getElementById("toggle-dashboard-btn");
  const metricsPanel = document.getElementById("metrics-panel");
  if (toggleDashboardBtn && metricsPanel) {
    toggleDashboardBtn.addEventListener("click", () => {
      if (metricsPanel.style.display === "none" || metricsPanel.style.display === "") {
        metricsPanel.style.display = "flex";
      } else {
        metricsPanel.style.display = "none";
      }
    });
  }

  // Browser FPS tracker loop
  let lastFrameTime = performance.now();
  let frameCount = 0;
  function updateFPS() {
    const now = performance.now();
    frameCount++;
    const fpsInterval = (window.VOICE_CONFIG.ui && window.VOICE_CONFIG.ui.fps_calc_interval_ms) || 1000;
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

  // Browser Event Loop Lag Tracker loop
  let lastLoopTime = performance.now();
  function checkLoopLag() {
    const now = performance.now();
    const lagInterval = (window.VOICE_CONFIG.ui && window.VOICE_CONFIG.ui.loop_lag_interval_ms) || 50;
    const lag = Math.max(0, now - lastLoopTime - lagInterval);
    const el = document.getElementById("browser-loop");
    if (el) el.textContent = lag.toFixed(1);
    lastLoopTime = now;
    setTimeout(checkLoopLag, lagInterval);
  }
  setTimeout(checkLoopLag, 50);

  // LiveKit SDK presence verification log
  const LK_LIBRARY = window.LivekitClient || window.LiveKitClient || window.LiveKit || window.Livekit;
  if (LK_LIBRARY) {
    console.log("[LiveKit] Client SDK verified and loaded successfully.");
    window.renderLogEvent({ event: "system", detail: { msg: "LiveKit Client SDK loaded successfully." } });
  } else {
    console.warn("[LiveKit] SDK not found. Falling back to REST/WebSocket pipeline only.");
    window.renderLogEvent({ event: "system", detail: { msg: "⚠️ LiveKit SDK not found — REST/WebSocket pipeline will be used." } });
  }
});
