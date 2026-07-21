// ---------------------------------------------------------------------------
// STT Manager - SpeechRecognition setup, VAD detection, verbal stop keywords,
// and sending transcripts via WebSocket or REST fallback.
//
// Interim-result debounce strategy:
//   interimResults = true so we see partial text in real time.
//   When interim text stabilises (unchanged for DEBOUNCE_MS), we fire it as
//   final immediately — cutting perceived STT latency from ~7s to ~600ms.
//   If the browser's own isFinal arrives first, we use that instead and
//   cancel the debounce timer.
// ---------------------------------------------------------------------------

window.sttEnabled = true;

// Debounce tunable — how long interim text must stay stable before we send it
const STT_DEBOUNCE_MS = 600;

// Per-recognition state for the debounce mechanism
window._sttDebounceTimer = null;
window._sttLastInterim = "";
window._sttAlreadySentForUtterance = false;

window.notifyBargeIn = async function() {
  // Immediately increment the client-side turn ID so any in-flight audio
  // chunks from the old turn are rejected locally without waiting for the
  // server's stop_audio message.
  window.currentServerTurnId++;
  window.awaitingNewTurn = true;

  window.stopAllQueuedAudio();
  if (window.streamSocket && window.streamSocket.readyState === WebSocket.OPEN) {
    window.streamSocket.send(JSON.stringify({
      type: "cancel",
      session_id: window.sessionId,
      reason: "vad_interrupted"
    }));
  }
  const cancelUrl = `http://${window.location.hostname || "localhost"}:${window.API_PORT}/control/cancel`;
  try {
    await fetch(cancelUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: window.sessionId,
        reason: "vad_interrupted"
      })
    });
    window.renderLogEvent({ event: "barge_in", detail: { msg: "Barge-in cancellation dispatched to Gateway." } });
  } catch (e) {
    console.error("[BargeIn] Failed to notify gateway of barge-in:", e);
  }
};

window.startSpeechRecognition = function() {
  console.log("[STT] Starting speech recognition...");
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    const msg = "SpeechRecognition is not supported in this browser. Please use Chrome or Edge.";
    window.renderLogEvent({ event: "error", detail: { message: msg } });
    console.error("[STT]", msg);
    return;
  }
  
  window.recognition = new SpeechRecognition();
  window.recognition.continuous = true;
  window.recognition.interimResults = true;   // ← KEY CHANGE: see interim results
  window.recognition.lang = window.VOICE_CONFIG.stt_language || 'en-US';
  
  window.recognition.onstart = () => {
    console.log("[STT] Recognition started — listening for speech");
    window.renderLogEvent({ event: "stt_started", detail: { msg: "Speech recognition active. Speak into your mic!" } });
    window.updateUIState("connected", "Listening...");
  };
  
  window.recognition.onspeechstart = () => {
    const interruptStart = performance.now();
    window.speechStartTime = performance.now();
    window._sttAlreadySentForUtterance = false;
    window._sttLastInterim = "";
    console.log("[STT] Speech detected (VAD start)");
    window.renderLogEvent({ event: "vad_start", detail: { msg: "Speech detected" } });
    
    const ids = ["wf-vad-start", "wf-stt-complete", "wf-llm-first-token", "wf-llm-complete", "wf-tts-first-audio", "wf-playback-start", "wf-playback-end", "wf-orch-start", "wf-tts-complete"];
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (el && el.parentElement) {
        el.parentElement.style.opacity = "0.45";
      }
    });
    
    const vadStart = Math.round(performance.now() - window.speechStartTime);
    window.updateWaterfallEl("wf-vad-start", `+${vadStart}ms`);
    
    if (window.dispatchTelemetryEvent) {
      window.dispatchTelemetryEvent("vad_start", {});
    }
    
    const statusBadge = document.getElementById("status-badge");
    const isAgentActive = window.currentAudio || (window.activeSources && window.activeSources.length > 0) || 
                          (statusBadge && (statusBadge.textContent === "Speaking..." || statusBadge.textContent === "Thinking..."));
    
    if (isAgentActive) {
      console.log("[STT] Speech detected — checking for interruption delay...");
      const delayMs = window.GLOBAL_BARGEIN_DELAY || 0;
      
      const interruptAction = () => {
        if (window.currentAudio) {
          window.currentAudio.pause();
          window.currentAudio = null;
        }
        
        const interruptLatency = Math.round(performance.now() - interruptStart);
        window.localHistory.interruption.push(interruptLatency);
        
        window.renderLogEvent({ event: "barge_in", detail: { msg: `Speech detected: Interrupted playback/generation in ${interruptLatency}ms.` } });
        window.notifyBargeIn();
      };
      
      if (delayMs > 0) {
        setTimeout(interruptAction, delayMs);
      } else {
        interruptAction();
      }
    }
  };
  
  // -----------------------------------------------------------------------
  // Core result handler — processes both interim and final results
  // -----------------------------------------------------------------------
  window.recognition.onresult = async (event) => {
    // If starting a fresh speech turn, reset turn timing and waterfall elements
    if (!window._turnInProgress) {
      window._turnInProgress = true;
      window.currentTurnIndex = (window.currentTurnIndex || 0) + 1;
      window.speechStartTime = performance.now();
      window._sttAlreadySentForUtterance = false;
      window._ttsFirstAudioFired = false;
      window._playbackStartFired = false;
      window._turnRecorded = false;
      if (window.clearWaterfall) window.clearWaterfall();
      if (window.updateWaterfallEl) window.updateWaterfallEl("wf-vad-start", "+0ms");
    }

    let interimText = "";
    let finalText = "";

    for (let i = event.resultIndex; i < event.results.length; ++i) {
      const res = event.results[i];
      if (res.isFinal) {
        finalText += res[0].transcript;
      } else {
        interimText += res[0].transcript;
      }
    }

    const userTranscriptDiv = document.getElementById("user-transcript");

    // Render interim text smoothly for immediate visual feedback without jitter
    if (interimText && !finalText) {
      window._sttLastInterim = interimText.trim();
      if (userTranscriptDiv) {
        userTranscriptDiv.innerHTML = `<span style="opacity: 0.7; font-style: italic;">${window._sttLastInterim}...</span>`;
      }

      // Safety timeout: if browser is slow to finalize after speech stops (1200ms pause), dispatch interim
      if (window._sttDebounceTimer) clearTimeout(window._sttDebounceTimer);
      window._sttDebounceTimer = setTimeout(() => {
        if (!window._sttAlreadySentForUtterance && window._sttLastInterim) {
          console.log(`[STT] Speech pause detected — dispatching stabilized transcript: "${window._sttLastInterim}"`);
          window._sttAlreadySentForUtterance = true;
          _dispatchTranscript(window._sttLastInterim);
        }
      }, 1200);

      return;
    }

    if (finalText.trim()) {
      if (window._sttDebounceTimer) {
        clearTimeout(window._sttDebounceTimer);
        window._sttDebounceTimer = null;
      }

      if (window._sttAlreadySentForUtterance) {
        console.log("[STT] Skipping browser isFinal — utterance already dispatched.");
        window._sttAlreadySentForUtterance = false;
        return;
      }

      window._sttAlreadySentForUtterance = false;
      _dispatchTranscript(finalText.trim());
    }
  };
  
  // -----------------------------------------------------------------------
  // _dispatchTranscript — shared logic for sending final text to pipeline
  // -----------------------------------------------------------------------
  async function _dispatchTranscript(transcript) {
    const sttEndTime = performance.now();
    
    const lowerTranscript = transcript.toLowerCase();
    const explicitStopKeywords = ["stop", "wait stop", "stop now", "shut up", "quiet", "cancel", "stop speaking", "pause", "wait stop now"];
    const isExplicitStop = explicitStopKeywords.some(kw => lowerTranscript.includes(kw));

    const userTranscriptDiv = document.getElementById("user-transcript");

    if (isExplicitStop) {
      console.log(`[STT] Explicit stop signal detected in transcript: "${transcript}" — stopping agent immediately!`);
      window.notifyBargeIn();
      if (userTranscriptDiv) userTranscriptDiv.textContent = `${transcript} 🛑 (Agent Stopped)`;
      window.renderLogEvent({ event: "barge_in", detail: { msg: `Interrupted via verbal stop command: "${transcript}"` } });
      window.updateUIState("connected", "Listening...");
      return;
    }
    
    const fallbackStt = window.VOICE_CONFIG.fallback_stt_latency || 180;
    const sttLatency = window.speechStartTime > 0 ? Math.round(sttEndTime - window.speechStartTime) : fallbackStt;
    window.localHistory.stt.push(sttLatency);
    
    console.log(`[STT] Final transcript: "${transcript}" (STT latency: ${sttLatency}ms)`);
    window.updateWaterfallEl("wf-stt-complete", `+${sttLatency}ms`);
    
    if (userTranscriptDiv) userTranscriptDiv.textContent = transcript;
    window.renderLogEvent({ event: "stt_final", detail: { text: transcript, latency_ms: sttLatency } });
    
    window.updateUIState("thinking", "Thinking...");
    
    const startFetch = performance.now();
    if (window.speechStartTime === 0) window.speechStartTime = startFetch;
    window.timeOrchStart = Math.round(startFetch - window.speechStartTime);
    const elOrch = document.getElementById("wf-orch-start") || document.getElementById("wf-vad-start");
    if (elOrch) {
      window.updateWaterfallEl(elOrch.id, `+${window.timeOrchStart}ms`);
    }

    if (window.streamSocket && window.streamSocket.readyState === WebSocket.OPEN) {
      console.log("[WS] Sending transcript via WebSocket pipeline");
      window.renderLogEvent({ event: "llm_request_sent", detail: { path: "websocket", text: transcript.slice(0, 60) } });
      window.streamSocket.send(JSON.stringify({
        type: "transcript",
        session_id: window.sessionId,
        text: transcript
      }));
      return;
    }

    console.log("[REST] WebSocket not available, falling back to /chat REST endpoint");
    window.renderLogEvent({ event: "llm_request_sent", detail: { path: "rest", text: transcript.slice(0, 60) } });
    const chatUrl = `http://${window.location.hostname || "localhost"}:${window.API_PORT}/chat`;
    try {
      const response = await fetch(chatUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: window.sessionId,
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
      window.localHistory.network.push(networkRTT);
      
      console.log(`[REST] Reply received: "${data.reply}" | LLM: ${data.llm_latency}ms | TTS: ${data.tts_latency}ms`);
      window.renderLogEvent({ event: "llm_response", detail: { text: data.reply, llm_ms: data.llm_latency, tts_ms: data.tts_latency } });
      
      const llmLate = data.llm_latency || 0;
      const ttsLate = data.tts_latency || 0;
      const llmFinish = window.timeOrchStart + llmLate;
      const ttsFinish = window.timeOrchStart + llmLate + ttsLate;
      window.updateWaterfallEl("wf-llm-complete", `+${llmFinish}ms`);
      const elTts = document.getElementById("wf-tts-complete") || document.getElementById("wf-tts-first-audio");
      if (elTts) {
        window.updateWaterfallEl(elTts.id, `+${ttsFinish}ms`);
      }
      
      const agentResponseDiv = document.getElementById("agent-response");
      if (agentResponseDiv) agentResponseDiv.textContent = data.reply;
      
      if (data.audio && data.audio.length > 0) {
        console.log("[REST] TTS audio received, playing...");
        window.renderLogEvent({ event: "tts_audio_received", detail: { bytes_b64: data.audio.length } });
        window.playBase64Audio(data.audio);
      } else {
        console.warn("[REST] No audio in response. tts_error:", data.tts_error);
        if (data.tts_error) {
          window.renderLogEvent({ event: "error", detail: { message: `TTS failed: ${data.tts_error}` } });
        }
        window.updateUIState("connected", "Listening...");
      }
    } catch (err) {
      console.error("[REST] Turn fetch failed:", err);
      window.renderLogEvent({ event: "error", detail: { message: `Voice processing failed: ${err.message}` } });
      window.updateUIState("connected", "Listening...");
    }
  }
  
  window.recognition.onerror = (e) => {
    if (e.error !== 'no-speech' && e.error !== 'aborted') {
      console.error("[STT] Recognition error:", e.error);
      window.renderLogEvent({ event: "error", detail: { message: `Speech recognition error: ${e.error}` } });
    } else {
      console.log(`[STT] Recognition lifecycle event: ${e.error} (auto-restarting)`);
    }
  };
  
  window.recognition.onend = () => {
    console.log("[STT] Recognition ended. sessionActive:", window.sessionActive, "sttEnabled:", window.sttEnabled);
    // Clear any pending debounce on recognition end
    if (window._sttDebounceTimer) {
      clearTimeout(window._sttDebounceTimer);
      window._sttDebounceTimer = null;
    }
    if (window.sttEnabled && window.sessionActive) {
      try {
        window.recognition.start();
      } catch (e) {
        console.warn("[STT] Could not restart recognition:", e.message);
      }
    }
  };
  
  try {
    window.recognition.start();
  } catch (e) {
    console.error("[STT] Failed to start recognition:", e);
    window.renderLogEvent({ event: "error", detail: { message: `Failed to start STT: ${e.message}` } });
  }
};
