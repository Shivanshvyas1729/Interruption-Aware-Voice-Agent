// ---------------------------------------------------------------------------
// WebRTC Manager - LiveKit room setups, credentials fetching, mic controls
// ---------------------------------------------------------------------------

window.fetchToken = async function(sessionId, roomName) {
  const url = `http://${window.location.hostname || "localhost"}:${window.API_PORT}/auth`;
  console.log("[Auth] Requesting LiveKit token from:", url);
  window.updateUIState("connecting", "Retrieving Token...");
  window.renderLogEvent({ event: "auth_request", detail: { msg: "Requesting LiveKit token from API Gateway...", url } });
  
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
    window.renderLogEvent({ event: "auth_success", detail: { msg: "Token successfully retrieved." } });
    window.renderLogEvent({ event: "system", detail: { msg: `LLM: ${data.llm_provider} (${data.llm_model}) | TTS: ${data.tts_provider} | STT: ${data.stt_provider}` } });
    
    return { token: data.token, livekitUrl: data.livekit_url };
  } catch (err) {
    console.error("[Auth] Token fetch failed:", err);
    throw new Error(`Failed to connect to API Gateway at ${url}. Ensure the gateway is running on port ${window.API_PORT}. Details: ${err.message}`);
  }
};

window.connectToRoom = async function(token, livekitUrl) {
  const LK = window.LivekitClient || window.LiveKitClient || window.LiveKit || window.Livekit;
  if (!LK) {
    console.warn("[LiveKit] SDK not found — skipping WebRTC room connection");
    window.renderLogEvent({ event: "system", detail: { msg: "LiveKit SDK unavailable — using REST/WebSocket pipeline only." } });
    return;
  }
  
  const { Room, RoomEvent } = LK;
  window.room = new Room();
  const audioEl = document.getElementById("agent-audio");
  
  window.room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
    if (window.room.localParticipant && participant.identity === window.room.localParticipant.identity) {
      console.log("[LiveKit] Ignored subscribing to our own track to prevent loopback/echo");
      return;
    }
    if (track.kind === "audio") {
      if (audioEl) track.attach(audioEl);
      console.log("[LiveKit] Audio track subscribed from:", participant.identity);
      window.renderLogEvent({ event: "track_subscribed", detail: { track_kind: "audio", identity: participant.identity } });
    }
  });

  window.room.on(RoomEvent.ParticipantConnected, (participant) => {
    console.log("[LiveKit] Participant connected:", participant.identity);
    window.renderLogEvent({ event: "participant_connected", detail: { identity: participant.identity } });
  });

  window.room.on(RoomEvent.Disconnected, (reason) => {
    console.warn("[LiveKit] Room disconnected:", reason);
    window.renderLogEvent({ event: "room_disconnected", detail: { reason } });
  });

  const fallbackLkUrl = (window.VOICE_CONFIG.livekit_url) || `ws://${window.location.hostname || "localhost"}:7800`;
  const url = livekitUrl || fallbackLkUrl;
  console.log("[LiveKit] Connecting browser WebRTC to:", url);
  window.renderLogEvent({ event: "livekit_connecting", detail: { url } });
  
  try {
    await window.room.connect(url, token);
    console.log("[LiveKit] Room connected:", window.room.name);
    window.renderLogEvent({ event: "room_joined", detail: { room: window.room.name } });
    
    await window.room.localParticipant.setMicrophoneEnabled(true);
    console.log("[LiveKit] Microphone published to room");
    window.renderLogEvent({ event: "mic_published", detail: { room: window.room.name } });
  } catch (lkErr) {
    console.warn("[LiveKit] Room connection failed (non-fatal):", lkErr.message);
    window.renderLogEvent({ event: "livekit_error", detail: { msg: `LiveKit failed (non-fatal): ${lkErr.message}. STT/TTS still active.` } });
  }
};

window.leaveSession = function() {
  console.log("[Session] Leaving session...");
  window.sessionActive = false;
  if (window.recognition) {
    try { window.recognition.stop(); } catch(e) {}
  }
  if (window.streamSocket) {
    try { window.streamSocket.close(); } catch(e) {}
    window.streamSocket = null;
  }
  if (window.room) {
    try { window.room.disconnect(); } catch(e) {}
    window.room = null;
  }
  window.stopAllQueuedAudio();
  if (window.stopMicEnergyTracker) {
    window.stopMicEnergyTracker();
  }
  window.updateUIState("disconnected", "Disconnected");
  
  const joinBtn = document.getElementById("join-btn");
  if (joinBtn) {
    joinBtn.disabled = false;
    joinBtn.querySelector("span").textContent = "Join Session";
    joinBtn.style.background = "linear-gradient(135deg, #3b82f6, #8b5cf6)";
  }
  window.renderLogEvent({ event: "session_ended", detail: { session_id: window.sessionId } });

  // Preserve session metrics history across disconnects so report downloads include all turns
  if (window.sessionMetricsHistory) {
    window.sessionMetricsHistory.system_snapshots = [];
  }
};
