// ---------------------------------------------------------------------------
// Audio Manager - handles WebSocket streaming, Web Audio playback, chunk decoding,
// and natural soft/instant interruption cutoffs.
// ---------------------------------------------------------------------------

window.connectWebSocketStream = function() {
  window.awaitingNewTurn = false;
  const wsUrl = `ws://${window.location.hostname || "localhost"}:${window.API_PORT}/stream`;
  console.log("[WS] Connecting to WebSocket streaming pipeline:", wsUrl);
  window.renderLogEvent({ event: "ws_connecting", detail: { url: wsUrl } });
  window.streamSocket = new WebSocket(wsUrl);
  
  window.streamSocket.onopen = () => {
    console.log("[WS] WebSocket streaming pipeline connected");
    const badge = document.getElementById("streaming-badge");
    if (badge) {
      badge.textContent = "Pipeline: WEBSOCKET STREAMING 🟢";
      badge.style.color = "#10b981";
    }
    window.renderLogEvent({ event: "ws_connected", detail: { url: wsUrl } });
    
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!window.audioContext) {
      window.audioContext = new AudioCtx();
    }
    const unlockAudio = () => {
      if (window.audioContext && window.audioContext.state === "suspended") {
        window.audioContext.resume().then(() => {
          console.log("[Audio] AudioContext resumed after user gesture");
        });
      }
    };
    unlockAudio();
    document.addEventListener("click", unlockAudio);
    document.addEventListener("pointerdown", unlockAudio);
    document.addEventListener("touchstart", unlockAudio);
    window.audioStartTime = window.audioContext.currentTime;
  };
  
  window.streamSocket.onmessage = async (event) => {
    if (typeof event.data === "string") {
      const msg = JSON.parse(event.data);
      console.log("[WS] Received string message:", msg.type);
      if (msg.type === "stop_audio") {
        if (msg.turn_id !== undefined) {
          window.currentServerTurnId = msg.turn_id;
        }
        window.stopAllQueuedAudio();
      } else if (msg.type === "llm_response") {
        window.awaitingNewTurn = false;
        if (msg.turn_id !== undefined) {
          window.currentServerTurnId = msg.turn_id;
        }
        console.log("[WS] LLM response received:", msg.text);
        window.renderLogEvent({ event: "llm_response", detail: { text: msg.text } });
        const agentResponseDiv = document.getElementById("agent-response");
        if (agentResponseDiv) {
          agentResponseDiv.textContent = msg.text;
          agentResponseDiv.classList.remove("empty");
        }
        
        const modelEl = document.getElementById("llm-model");
        const tokensEl = document.getElementById("llm-tokens");
        const latencyEl = document.getElementById("llm-latency");
        if (modelEl) modelEl.textContent = window.VOICE_CONFIG.llm_model || "llama-3.3-70b-versatile";
        if (tokensEl) tokensEl.textContent = msg.tokens || "-";
        if (latencyEl) latencyEl.textContent = (msg.latency_ms ? msg.latency_ms + "ms" : "-");
        
        // Handle LLM-directed system pause command
        if (msg.pause_duration_ms && msg.pause_duration_ms > 0) {
          console.log("[Audio] Suspending playback for", msg.pause_duration_ms, "ms by LLM directive.");
          window.renderLogEvent({ event: "system_pause", detail: { duration_ms: msg.pause_duration_ms } });
          if (window.audioContext) {
            window.audioContext.suspend().catch(e => console.warn(e));
          }
          if (window.pauseTimeout) clearTimeout(window.pauseTimeout);
          if (window.countdownInterval) clearInterval(window.countdownInterval);

          let remainingMs = msg.pause_duration_ms;
          const updateTimerText = () => {
            window.updateUIState("thinking", `Paused (${(remainingMs / 1000).toFixed(1)}s)...`);
          };
          updateTimerText();

          window.countdownInterval = setInterval(() => {
            remainingMs -= 100;
            if (remainingMs <= 0) {
              clearInterval(window.countdownInterval);
              window.countdownInterval = null;
            } else {
              updateTimerText();
            }
          }, 100);

          window.pauseTimeout = setTimeout(async () => {
            if (window.countdownInterval) {
              clearInterval(window.countdownInterval);
              window.countdownInterval = null;
            }
            if (window.audioContext && window.audioContext.state === "suspended") {
              await window.audioContext.resume().catch(e => console.warn(e));
              window.updateUIState("speaking", "Speaking...");
            }
          }, msg.pause_duration_ms);
        }
        
        window.resumeAudioOnBargeIn = async function() {
          if (window.countdownInterval) {
            clearInterval(window.countdownInterval);
            window.countdownInterval = null;
          }
          if (window.pauseTimeout) {
            clearTimeout(window.pauseTimeout);
            window.pauseTimeout = null;
          }
          if (window.audioContext && window.audioContext.state === "suspended") {
            await window.audioContext.resume().catch(e => console.warn(e));
          }
        };
        
        const nowIst = window.formatIST ? window.formatIST() : new Date().toLocaleTimeString();
        window._llmFirstTokenIso = nowIst;
        window._llmCompleteIso = nowIst;
        // Update waterfall offsets for LLM stage in WebSocket streaming path
        if (window.speechStartTime > 0) {
          const nowOff = Math.round(performance.now() - window.speechStartTime);
          // LLM first token ≈ orchestration start + server LLM latency
          if (msg.latency_ms) {
            const llmFirstTokenOff = (window.timeOrchStart || 0) + Math.round(msg.latency_ms * 0.3);
            window.updateWaterfallEl("wf-llm-first-token", `+${llmFirstTokenOff}ms`);
          }
          // LLM complete = now (we just received the full response text)
          window.updateWaterfallEl("wf-llm-complete", `+${nowOff}ms`);
        }
        
        console.log("[WS] Updated Agent Response Panel with LLM response");
        window.renderLogEvent({ event: "agent_panel_updated", detail: { text: msg.text.slice(0, 60) } });
      } else if (msg.type === "error") {
        window.renderLogEvent({ event: "error", detail: { message: `Pipeline error: ${msg.detail}` } });
      }
    } else {
      const arrayBuffer = await event.data.arrayBuffer();
      if (arrayBuffer.byteLength < 4) return;
      const tagView = new DataView(arrayBuffer, 0, 4);
      const serverTurnId = tagView.getUint32(0, true);
      if (window.awaitingNewTurn && serverTurnId > window.currentServerTurnId) {
        console.log("[WS] Received first chunk of new turn", serverTurnId, "clearing awaitingNewTurn flag");
        window.awaitingNewTurn = false;
        window.currentServerTurnId = serverTurnId;
      }
      if (window.awaitingNewTurn || serverTurnId < window.currentServerTurnId) {
        console.log("[WS] Discarding stale audio frame for turn", serverTurnId,
                    "(current:", window.currentServerTurnId, ", awaitingNewTurn:", window.awaitingNewTurn, ")");
        return;
      }
      const pcmBuffer = arrayBuffer.slice(4);
      if (pcmBuffer.byteLength === 0) return;
      console.log("[WS] Received audio chunk, size:", pcmBuffer.byteLength, "turn:", serverTurnId);
      window.renderLogEvent({ event: "audio_chunk_received", detail: { size: pcmBuffer.byteLength } });
      
      // Update TTS first audio waterfall on the very first audio chunk of a turn
      if (!window._ttsFirstAudioFired) {
        window._ttsFirstAudioFired = true;
        window._ttsFirstAudioIso = window.formatIST ? window.formatIST() : new Date().toLocaleTimeString();
        if (window.speechStartTime > 0) {
          const ttsOff = Math.round(performance.now() - window.speechStartTime);
          const sttOff = Math.round((window.timeOrchStart || 0));
          const validTtsOff = Math.max(sttOff + 50, ttsOff);
          window.updateWaterfallEl("wf-tts-first-audio", `+${validTtsOff}ms`);
        }
      }
      window.decodeAndScheduleChunk(pcmBuffer);
    }
  };
  
  window.streamSocket.onerror = (e) => {
    console.error("[WS] WebSocket stream error:", e);
    window.renderLogEvent({ event: "error", detail: { message: "WebSocket stream error. Falling back to REST." } });
  };
  
  window.streamSocket.onclose = (e) => {
    console.log("[WS] WebSocket stream closed:", e.code, e.reason);
    const badge = document.getElementById("streaming-badge");
    if (badge) {
      badge.textContent = "Pipeline: REST";
      badge.style.color = "#a3a3a3";
    }
    window.renderLogEvent({ event: "ws_disconnected", detail: { code: e.code, reason: e.reason || "connection closed" } });
    window.streamSocket = null;
  };
};

window.decodeAndScheduleChunk = async function(arrayBuffer) {
  if (!window.audioContext) {
    console.warn("[Audio] No AudioContext available, skipping chunk");
    return;
  }
  const myGeneration = window.playbackGeneration;

  if (window.audioContext.state === "suspended") {
    try {
      await window.audioContext.resume();
    } catch (e) {
      console.warn("[Audio] Could not resume AudioContext:", e);
    }
    if (window.playbackGeneration !== myGeneration) return;
  }
  try {
    let combinedBuffer = arrayBuffer;
    
    if (window.leftoverBytes) {
      const tmp = new Uint8Array(window.leftoverBytes.length + arrayBuffer.byteLength);
      tmp.set(window.leftoverBytes, 0);
      tmp.set(new Uint8Array(arrayBuffer), window.leftoverBytes.length);
      combinedBuffer = tmp.buffer;
      window.leftoverBytes = null;
    }
    
    if (combinedBuffer.byteLength % 2 !== 0) {
      window.leftoverBytes = new Uint8Array(combinedBuffer, combinedBuffer.byteLength - 1, 1);
      combinedBuffer = combinedBuffer.slice(0, combinedBuffer.byteLength - 1);
    }
    
    if (combinedBuffer.byteLength < 4) {
      return;
    }
    
    let audioBuffer;
    const headerView = new Uint8Array(combinedBuffer, 0, 4);
    const isWav = headerView[0] === 0x52 && // 'R'
                  headerView[1] === 0x49 && // 'I'
                  headerView[2] === 0x46 && // 'F'
                  headerView[3] === 0x46;   // 'F'
                  
    if (isWav) {
      audioBuffer = await window.audioContext.decodeAudioData(combinedBuffer);
      if (window.playbackGeneration !== myGeneration) return;
    } else {
      const intData = new Int16Array(combinedBuffer);
      const floatData = new Float32Array(intData.length);
      for (let i = 0; i < intData.length; i++) {
        floatData[i] = intData[i] / 32768.0;
      }
      audioBuffer = window.audioContext.createBuffer(1, floatData.length, 24000);
      audioBuffer.copyToChannel(floatData, 0);
    }
    
    if (window.playbackGeneration !== myGeneration) return;

    const source = window.audioContext.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(window.audioContext.destination);
    
    const now = window.audioContext.currentTime;
    if (window.audioStartTime < now) {
      window.audioStartTime = now;
    }
    
    source.start(window.audioStartTime);
    window.activeSources.push(source);
    
    window.audioStartTime += audioBuffer.duration;
    window.updateUIState("speaking", "Speaking...");
    
    if (window.dispatchTelemetryEvent && window.activeSources.length === 1) {
      window._playbackStartIso = window.formatIST ? window.formatIST() : new Date().toLocaleTimeString();
      window.dispatchTelemetryEvent("playback_start", {});
      window.renderLogEvent({ event: "playback_started", detail: { source: "websocket_chunk" } });
      // Update playback start waterfall
      if (window.speechStartTime > 0) {
        const pbOff = Math.round(performance.now() - window.speechStartTime);
        window.updateWaterfallEl("wf-playback-start", `+${pbOff}ms`);
      }
    }
    
    source.onended = () => {
      window.activeSources = window.activeSources.filter(s => s !== source);
      if (window.activeSources.length === 0) {
        console.log("[Audio] All audio chunks played");
        window._playbackEndIso = window.formatIST ? window.formatIST() : new Date().toLocaleTimeString();
        window.renderLogEvent({ event: "playback_completed", detail: { source: "websocket_chunk" } });
        window.updateUIState("connected", "Listening...");
        // Update playback end waterfall
        if (window.speechStartTime > 0) {
          const pbEndOff = Math.round(performance.now() - window.speechStartTime);
          window.updateWaterfallEl("wf-playback-end", `+${pbEndOff}ms`);
        }
        window._turnInProgress = false;
        if (window.dispatchTelemetryEvent) {
          window.dispatchTelemetryEvent("playback_end", {});
        }
      }
    };
  } catch (e) {
    console.error("[Audio] Failed to decode audio chunk:", e.message);
    window.renderLogEvent({ event: "error", detail: { message: `Audio decode failed: ${e.message}` } });
    if (window.activeSources.length === 0) {
      window.updateUIState("connected", "Listening...");
    }
  }
};

window.playBase64Audio = function(base64Data) {
  console.log("[Audio] playBase64Audio called, data length:", base64Data.length);
  try {
    if (window.currentAudio) {
      window.currentAudio.pause();
      window.currentAudio = null;
    }
    
    const binaryString = window.atob(base64Data);
    const len = binaryString.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    
    const blob = new Blob([bytes.buffer], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    window.currentAudio = new Audio(url);
    
    window.currentAudio.onplay = () => {
      console.log("[Audio] Playback started");
      window.renderLogEvent({ event: "playback_started", detail: { source: "base64_wav" } });
      window.updateUIState("speaking", "Speaking...");
      
      if (window.dispatchTelemetryEvent) {
        window.dispatchTelemetryEvent("playback_start", {});
      }
      
      if (window.speechStartTime > 0) {
        const playbackStart = Math.round(performance.now() - window.speechStartTime);
        window.updateWaterfallEl("wf-playback-start", `+${playbackStart}ms`);
      }
    };
    
    window.currentAudio.onended = () => {
      console.log("[Audio] Playback ended");
      window.renderLogEvent({ event: "playback_completed", detail: { source: "base64_wav" } });
      window.updateUIState("connected", "Listening...");
      window.currentAudio = null;
      if (window.dispatchTelemetryEvent) {
        window.dispatchTelemetryEvent("playback_end", {});
      }
    };
    
    window.currentAudio.onerror = (e) => {
      console.error("[Audio] Audio element error:", e);
      window.renderLogEvent({ event: "error", detail: { message: `Audio element error: ${e.type}` } });
      window.updateUIState("connected", "Listening...");
    };
    
    const playPromise = window.currentAudio.play();
    if (playPromise !== undefined) {
      playPromise.catch(err => {
        console.error("[Audio] Audio playback failed (autoplay policy?):", err.message);
        window.renderLogEvent({ event: "error", detail: { message: `Audio playback failed: ${err.message}. Click the page to allow audio.` } });
        window.updateUIState("connected", "Listening...");
      });
    }
  } catch (e) {
    console.error("[Audio] Failed to decode base64 audio:", e);
    window.renderLogEvent({ event: "error", detail: { message: `Failed to decode TTS audio: ${e.message}` } });
    window.updateUIState("connected", "Listening...");
  }
};

window.stopAllQueuedAudio = function() {
  window.playbackGeneration++;
  window.awaitingNewTurn = true;
  window._ttsFirstAudioFired = false;  // Reset so next turn's first chunk triggers waterfall
  
  if (window.currentAudio) {
    try {
      window.currentAudio.pause();
      window.currentAudio.currentTime = 0;
    } catch (e) {}
    window.currentAudio = null;
  }
  const audioEl = document.getElementById("agent-audio");
  if (audioEl) {
    try {
      audioEl.pause();
      audioEl.currentTime = 0;
    } catch (e) {}
  }

  const cutoffMode = window.GLOBAL_CUTOFF_MODE || "instant";
  const sourcesToStop = [...window.activeSources];
  const hadActive = window.activeSources.length > 0;
  
  window.activeSources = [];
  window.leftoverBytes = null;
  window.audioStartTime = window.audioContext ? window.audioContext.currentTime : 0;
  
  const executeStop = () => {
    sourcesToStop.forEach(source => {
      try {
        source.stop();
      } catch (e) {}
    });
    window.updateUIState("connected", "Listening...");
    if (hadActive && window.dispatchTelemetryEvent) {
      window.dispatchTelemetryEvent("cancellation", { reason: "user_stop" });
    }
  };

  if (cutoffMode === "soft" && hadActive) {
    setTimeout(executeStop, 50);
  } else {
    executeStop();
  }
};
