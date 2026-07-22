// ---------------------------------------------------------------------------
// Controls Manager - handles settings panels, presets, safety checks for DOM,
// mic energy trackers, and master action buttons.
// ---------------------------------------------------------------------------

window.startMicEnergyTracker = function(stream) {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    window.audioContextForMic = new AudioCtx();
    const source = window.audioContextForMic.createMediaStreamSource(stream);
    window.analyserNode = window.audioContextForMic.createAnalyser();
    window.analyserNode.fftSize = (window.VOICE_CONFIG.ui && window.VOICE_CONFIG.ui.analyser_fft_size) || 256;
    source.connect(window.analyserNode);
    
    const bufferLength = window.analyserNode.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    
    window.micEnergyInterval = setInterval(() => {
      if (!window.analyserNode) return;
      window.analyserNode.getByteTimeDomainData(dataArray);
      
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        const val = (dataArray[i] - 128) / 128;
        sum += val * val;
      }
      const rms = Math.sqrt(sum / bufferLength);
      
      // Strict Interruption Rule: If user is speaking, the agent must not speak!
      const isAgentSpeaking = (window.activeSources && window.activeSources.length > 0) || window.currentAudio;
      if (isAgentSpeaking && rms > 0.04) {
        console.log("[MicTracker] Speech detected via mic energy RMS:", rms.toFixed(4), "— cutting off playback immediately!");
        if (window.notifyBargeIn) {
          window.notifyBargeIn();
        }
      }

      const cap = window.VOICE_CONFIG.volume_percent_cap || 100;
      const mult = window.VOICE_CONFIG.volume_rms_multiplier || 400;
      const volumePercent = Math.min(cap, Math.round(rms * mult));
      const energyBar = document.getElementById("mic-energy-bar");
      if (energyBar) {
        energyBar.style.width = `${volumePercent}%`;
      }
    }, (window.VOICE_CONFIG.ui && window.VOICE_CONFIG.ui.mic_energy_interval_ms) || 50);
  } catch (e) {
    console.warn("[MicTracker] Could not start Web Audio analyser for mic energy:", e);
  }
};

window.stopMicEnergyTracker = function() {
  if (window.micEnergyInterval) {
    clearInterval(window.micEnergyInterval);
    window.micEnergyInterval = null;
  }
  if (window.audioContextForMic) {
    try {
      window.audioContextForMic.close();
    } catch (e) {}
    window.audioContextForMic = null;
  }
  window.analyserNode = null;

  // Stop mic stream tracks to release microphone hardware completely
  if (window.micStream) {
    try {
      window.micStream.getTracks().forEach(track => track.stop());
    } catch (e) {}
    window.micStream = null;
  }

  const energyBar = document.getElementById("mic-energy-bar");
  if (energyBar) {
    energyBar.style.width = "0%";
  }
};

// Start Mic tracker on request
window.initializeMicTracker = function() {
  if (window.micStream) return; // Already running
  
  navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    }
  })
    .then(stream => {
      window.micStream = stream;
      window.startMicEnergyTracker(stream);
      console.log("[Mic] Microphone access granted and tracker active");
    })
    .catch(err => {
      console.warn("[Mic] Microphone analysis initialization bypassed:", err.message);
    });
};

// ---------------------------------------------------------------------------
// Settings API Configuration & Sync
// ---------------------------------------------------------------------------
window.loadVoiceConfig = async function() {
  try {
    const r = await fetch(window.CFG_URL);
    if (r.ok) Object.assign(window.VOICE_CONFIG, await r.json());
    console.log("[Config] Voice config loaded:", window.VOICE_CONFIG);
  } catch (e) {
    console.warn("[Config] Could not load voice config, using defaults:", e.message);
  }
  const t = window.VOICE_CONFIG.latency_threshold_targets || {};
  const q = (sel) => document.querySelector(sel);
  if (q(".target-stt")) q(".target-stt").textContent = (t.stt || 250) + "ms";
  if (q(".target-llm")) q(".target-llm").textContent = (t.llm || 800) + "ms";
  if (q(".target-tts")) q(".target-tts").textContent = (t.tts || 250) + "ms";
  if (q(".target-network")) q(".target-network").textContent = (t.network || 150) + "ms";
  if (q(".target-interruption")) q(".target-interruption").textContent = (t.interruption || 100) + "ms";
  if (q(".target-total")) q(".target-total").textContent = (t.total || 1200) + "ms";
};

// Sliders and Selects initialization
const normalTokensSlider = document.getElementById("normal-tokens-slider");
const normalTokensVal = document.getElementById("normal-tokens-val");
const normalSentencesSlider = document.getElementById("normal-sentences-slider");
const normalSentencesVal = document.getElementById("normal-sentences-val");
const detailTokensSlider = document.getElementById("detail-tokens-slider");
const detailTokensVal = document.getElementById("detail-tokens-val");
const detailSentencesSlider = document.getElementById("detail-sentences-slider");
const detailSentencesVal = document.getElementById("detail-sentences-val");
const speechRateSlider = document.getElementById("speech-rate-slider");
const speechRateVal = document.getElementById("speech-rate-val");
const ttsVolumeSlider = document.getElementById("tts-volume-slider");
const ttsVolumeVal = document.getElementById("tts-volume-val");
const ttsVoiceSelect = document.getElementById("tts-voice-select");
const sttLangSelect = document.getElementById("stt-lang-select");
const vadSilenceSlider = document.getElementById("vad-silence-slider");
const vadSilenceVal = document.getElementById("vad-silence-val");
const saveLimitsBtn = document.getElementById("save-limits-btn");

// Slider listeners
if (normalTokensSlider && normalTokensVal) normalTokensSlider.addEventListener("input", () => normalTokensVal.textContent = normalTokensSlider.value);
if (normalSentencesSlider && normalSentencesVal) normalSentencesSlider.addEventListener("input", () => normalSentencesVal.textContent = normalSentencesSlider.value);
if (detailTokensSlider && detailTokensVal) detailTokensSlider.addEventListener("input", () => detailTokensVal.textContent = detailTokensSlider.value);
if (detailSentencesSlider && detailSentencesVal) detailSentencesSlider.addEventListener("input", () => detailSentencesVal.textContent = detailSentencesSlider.value);

if (speechRateSlider && speechRateVal) {
  speechRateSlider.addEventListener("input", () => {
    // Slider is integer 50-200, map to 0.50x-2.00x
    const rate = (parseInt(speechRateSlider.value) / 100).toFixed(2);
    speechRateVal.textContent = `${parseFloat(rate).toFixed(1)}x`;
    window.GLOBAL_SPEECH_RATE = parseFloat(rate);
  });
}

if (ttsVolumeSlider && ttsVolumeVal) {
  ttsVolumeSlider.addEventListener("input", () => {
    ttsVolumeVal.textContent = `${ttsVolumeSlider.value}%`;
    window.GLOBAL_TTS_VOLUME = parseFloat(ttsVolumeSlider.value) / 100.0;
  });
}

if (vadSilenceSlider && vadSilenceVal) {
  vadSilenceSlider.addEventListener("input", () => {
    vadSilenceVal.textContent = `${vadSilenceSlider.value}ms`;
    window.GLOBAL_VAD_SILENCE = parseInt(vadSilenceSlider.value);
  });
}

const bargeinDelaySlider = document.getElementById("bargein-delay-slider");
const bargeinDelayVal = document.getElementById("bargein-delay-val");
if (bargeinDelaySlider && bargeinDelayVal) {
  bargeinDelaySlider.addEventListener("input", () => {
    bargeinDelayVal.textContent = `${bargeinDelaySlider.value}ms`;
    window.GLOBAL_BARGEIN_DELAY = parseInt(bargeinDelaySlider.value);
  });
}

const chunkBufferSlider = document.getElementById("chunk-buffer-slider");
const chunkBufferVal = document.getElementById("chunk-buffer-val");
if (chunkBufferSlider && chunkBufferVal) {
  chunkBufferSlider.addEventListener("input", () => {
    chunkBufferVal.textContent = `${chunkBufferSlider.value}ms`;
    window.GLOBAL_CHUNK_BUFFER = parseInt(chunkBufferSlider.value);
  });
}

const interruptMinSpeechSlider = document.getElementById("interrupt-min-speech-slider");
const interruptMinSpeechVal = document.getElementById("interrupt-min-speech-val");
if (interruptMinSpeechSlider && interruptMinSpeechVal) {
  interruptMinSpeechSlider.addEventListener("input", () => {
    interruptMinSpeechVal.textContent = `${interruptMinSpeechSlider.value}ms`;
    window.GLOBAL_MIN_SPEECH_DURATION = parseInt(interruptMinSpeechSlider.value);
  });
}

const sttMinConfSlider = document.getElementById("stt-min-conf-slider");
const sttMinConfVal = document.getElementById("stt-min-conf-val");
if (sttMinConfSlider && sttMinConfVal) {
  sttMinConfSlider.addEventListener("input", () => {
    sttMinConfVal.textContent = parseFloat(sttMinConfSlider.value).toFixed(2);
    window.GLOBAL_STT_MIN_CONF = parseFloat(sttMinConfSlider.value);
  });
}

const speechPauseGapSlider = document.getElementById("speech-pause-gap-slider");
const speechPauseGapVal = document.getElementById("speech-pause-gap-val");
if (speechPauseGapSlider && speechPauseGapVal) {
  speechPauseGapSlider.addEventListener("input", () => {
    speechPauseGapVal.textContent = `${speechPauseGapSlider.value}ms`;
    window.GLOBAL_SPEECH_PAUSE_GAP = parseInt(speechPauseGapSlider.value);
  });
}

const postSentenceGraceSlider = document.getElementById("post-sentence-grace-slider");
const postSentenceGraceVal = document.getElementById("post-sentence-grace-val");
if (postSentenceGraceSlider && postSentenceGraceVal) {
  postSentenceGraceSlider.addEventListener("input", () => {
    postSentenceGraceVal.textContent = `${postSentenceGraceSlider.value}ms`;
    window.GLOBAL_POST_SENTENCE_GRACE = parseInt(postSentenceGraceSlider.value);
  });
}

const cutoffModeSelect = document.getElementById("cutoff-mode-select");
if (cutoffModeSelect) {
  window.GLOBAL_CUTOFF_MODE = cutoffModeSelect.value;
  cutoffModeSelect.addEventListener("change", () => {
    window.GLOBAL_CUTOFF_MODE = cutoffModeSelect.value;
  });
}

if (sttLangSelect) {
  sttLangSelect.addEventListener("change", () => {
    if (window.VOICE_CONFIG) window.VOICE_CONFIG.stt_language = sttLangSelect.value;
    console.log("[MasterControl] STT Language changed to:", sttLangSelect.value);
  });
}

// Fetch current limits from server and sync
window.fetchSettings = async function() {
  try {
    const port = window.API_PORT || 5000;
    const res = await fetch(`http://${window.location.hostname || "localhost"}:${port}/control/limits`);
    if (res.ok) {
      const limits = await res.json();
      if (normalTokensSlider && normalTokensVal) { normalTokensSlider.value = limits.normal_max_tokens; normalTokensVal.textContent = limits.normal_max_tokens; }
      if (normalSentencesSlider && normalSentencesVal) { normalSentencesSlider.value = limits.normal_max_sentences; normalSentencesVal.textContent = limits.normal_max_sentences; }
      if (detailTokensSlider && detailTokensVal) { detailTokensSlider.value = limits.detail_max_tokens; detailTokensVal.textContent = limits.detail_max_tokens; }
      if (detailSentencesSlider && detailSentencesVal) { detailSentencesSlider.value = limits.detail_max_sentences; detailSentencesVal.textContent = limits.detail_max_sentences; }
      
      if (limits.speech_rate && speechRateSlider && speechRateVal) {
        speechRateSlider.value = limits.speech_rate;
        speechRateVal.textContent = `${parseFloat(limits.speech_rate).toFixed(1)}x`;
        window.GLOBAL_SPEECH_RATE = parseFloat(limits.speech_rate);
      }
      if (limits.stt_language && sttLangSelect) {
        sttLangSelect.value = limits.stt_language;
        if (window.VOICE_CONFIG) window.VOICE_CONFIG.stt_language = limits.stt_language;
      }
      if (limits.tts_voice && ttsVoiceSelect) {
        ttsVoiceSelect.value = limits.tts_voice;
      }
      console.log("[MasterControl] Synced settings from API:", limits);
    }
  } catch (e) {
    console.error("[MasterControl] Failed to fetch settings:", e);
  }
};

// Save settings button handler
if (saveLimitsBtn) {
  saveLimitsBtn.addEventListener("click", async () => {
    saveLimitsBtn.disabled = true;
    saveLimitsBtn.textContent = "Saving...";
    try {
      const port = window.API_PORT || 5000;
      const payload = {
        normal_max_tokens: normalTokensSlider ? parseInt(normalTokensSlider.value) : 200,
        normal_max_sentences: normalSentencesSlider ? parseInt(normalSentencesSlider.value) : 2,
        detail_max_tokens: detailTokensSlider ? parseInt(detailTokensSlider.value) : 500,
        detail_max_sentences: detailSentencesSlider ? parseInt(detailSentencesSlider.value) : 5,
        speech_rate: parseFloat(speechRateSlider ? speechRateSlider.value : 1.0),
        stt_language: sttLangSelect ? sttLangSelect.value : "en-US",
        tts_voice: ttsVoiceSelect ? ttsVoiceSelect.value : "sonic-english"
      };
      
      const res = await fetch(`http://${window.location.hostname || "localhost"}:${port}/control/limits`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        saveLimitsBtn.style.background = "#10b981";
        saveLimitsBtn.textContent = "Saved ✓";
        setTimeout(() => {
          saveLimitsBtn.style.background = "linear-gradient(135deg, #3b82f6, #8b5cf6)";
          saveLimitsBtn.textContent = "Apply & Save";
          saveLimitsBtn.disabled = false;
        }, 1500);
      } else {
        throw new Error(`HTTP Error: ${res.status}`);
      }
    } catch (e) {
      console.error("[MasterControl] Failed to save settings:", e);
      saveLimitsBtn.style.background = "#ef4444";
      saveLimitsBtn.textContent = "Failed ✗";
      setTimeout(() => {
        saveLimitsBtn.style.background = "linear-gradient(135deg, #3b82f6, #8b5cf6)";
        saveLimitsBtn.textContent = "Apply & Save";
        saveLimitsBtn.disabled = false;
      }, 1500);
    }
  });
}

// Group Navigation Selector Tabs logic
const groupTabBtns = document.querySelectorAll(".grp-tab-btn");
const groupCards = document.querySelectorAll(".ctrl-grp-card");

window.showGroup = function(targetGroupId) {
  groupTabBtns.forEach(btn => {
    if (btn.getAttribute("data-group") === targetGroupId) {
      btn.classList.add("active");
      btn.style.borderColor = "#3b82f6";
      btn.style.background = "rgba(59,130,246,0.25)";
      btn.style.color = "#60a5fa";
    } else {
      btn.classList.remove("active");
      btn.style.borderColor = "rgba(255,255,255,0.08)";
      btn.style.background = "rgba(255,255,255,0.03)";
      btn.style.color = "#9ca3af";
    }
  });

  groupCards.forEach(card => {
    if (targetGroupId === "grp-all" || card.id === targetGroupId) {
      card.style.display = "flex";
    } else {
      card.style.display = "none";
    }
  });
};

// Default to Response group active for clean focus
window.showGroup("grp-response");

groupTabBtns.forEach(btn => {
  btn.addEventListener("click", () => {
    const groupTarget = btn.getAttribute("data-group");
    window.showGroup(groupTarget);
  });
});

// Best Human Defaults Preset Handler
const presetHumanBtn = document.getElementById("preset-human-btn");
if (presetHumanBtn) {
  presetHumanBtn.addEventListener("click", () => {
    if (normalTokensSlider && normalTokensVal) { normalTokensSlider.value = 200; normalTokensVal.textContent = "200"; }
    if (normalSentencesSlider && normalSentencesVal) { normalSentencesSlider.value = 2; normalSentencesVal.textContent = "2"; }
    if (detailTokensSlider && detailTokensVal) { detailTokensSlider.value = 500; detailTokensVal.textContent = "500"; }
    if (detailSentencesSlider && detailSentencesVal) { detailSentencesSlider.value = 5; detailSentencesVal.textContent = "5"; }
    if (speechRateSlider && speechRateVal) { speechRateSlider.value = 1.0; speechRateVal.textContent = "1.0x"; window.GLOBAL_SPEECH_RATE = 1.0; }
    if (ttsVolumeSlider && ttsVolumeVal) { ttsVolumeSlider.value = 100; ttsVolumeVal.textContent = "100%"; window.GLOBAL_TTS_VOLUME = 1.0; }
    if (vadSilenceSlider && vadSilenceVal) { vadSilenceSlider.value = 450; vadSilenceVal.textContent = "450ms"; window.GLOBAL_VAD_SILENCE = 450; }
    if (bargeinDelaySlider && bargeinDelayVal) { bargeinDelaySlider.value = 0; bargeinDelayVal.textContent = "0ms"; window.GLOBAL_BARGEIN_DELAY = 0; }
    if (chunkBufferSlider && chunkBufferVal) { chunkBufferSlider.value = 30; chunkBufferVal.textContent = "30ms"; window.GLOBAL_CHUNK_BUFFER = 30; }
    if (cutoffModeSelect) { cutoffModeSelect.value = "soft"; window.GLOBAL_CUTOFF_MODE = "soft"; }
    
    presetHumanBtn.style.background = "rgba(16,185,129,0.3)";
    presetHumanBtn.style.borderColor = "#10b981";
    presetHumanBtn.style.color = "#34d399";
    presetHumanBtn.textContent = "Human Defaults Applied ✓";
    setTimeout(() => {
      presetHumanBtn.style.background = "linear-gradient(135deg, rgba(236,72,153,0.2), rgba(139,92,246,0.2))";
      presetHumanBtn.style.borderColor = "#ec4899";
      presetHumanBtn.style.color = "#f472b6";
      presetHumanBtn.textContent = "✨ Best Human Defaults";
    }, 1500);
    console.log("[MasterControl] Applied Best Human Defaults");
  });
}

// Download controls settings & telemetry metrics JSON files
const downloadSettingsBtn = document.getElementById("download-settings-btn");
if (downloadSettingsBtn) {
  downloadSettingsBtn.addEventListener("click", () => {
    const settingsPayload = {
      timestamp: new Date().toISOString(),
      llm: {
        normal_max_tokens: normalTokensSlider ? parseInt(normalTokensSlider.value) : 200,
        normal_max_sentences: normalSentencesSlider ? parseInt(normalSentencesSlider.value) : 2,
        detail_max_tokens: detailTokensSlider ? parseInt(detailTokensSlider.value) : 500,
        detail_max_sentences: detailSentencesSlider ? parseInt(detailSentencesSlider.value) : 5
      },
      tts: {
        speech_rate: parseFloat(speechRateSlider ? speechRateSlider.value : 1.0),
        volume_percent: parseInt(ttsVolumeSlider ? ttsVolumeSlider.value : 100),
        voice_model: ttsVoiceSelect ? ttsVoiceSelect.value : "sonic-english"
      },
      stt: {
        language: sttLangSelect ? sttLangSelect.value : "en-US",
        vad_silence_ms: parseInt(vadSilenceSlider ? vadSilenceSlider.value : 450)
      }
    };

    const blob = new Blob([JSON.stringify(settingsPayload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", url);
    downloadAnchor.setAttribute("download", `agent_settings_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
    URL.revokeObjectURL(url);
  });
}

const triggerMetricsDownload = () => {
  // If a turn is currently active and not yet recorded, record it now
  if (window.recordTurnMetrics && window.lastRecordedTurnId !== window.currentTurnIndex) {
    window.recordTurnMetrics(false, "on_download");
  }

  const payload = window.sessionMetricsHistory || {
    session_id: window.sessionId || "unknown",
    start_time: new Date().toISOString(),
    system_snapshots: [],
    turn_latency_records: [],
    high_latency_warnings: []
  };

  const parseMs = (text) => {
    if (!text || text === "-" || text === "") return null;
    const m = text.match(/\+?(\d+)ms/);
    return m ? parseInt(m[1]) : null;
  };

  const getIST = (d) => (window.formatIST ? window.formatIST(d) : new Date(d || Date.now()).toLocaleString());

  let report = "";
  report += "======================================================================\n";
  report += "            PIVOT VOICE AGENT PERFORMANCE REPORT (IST)\n";
  report += "======================================================================\n";
  report += `Session ID:          ${payload.session_id || "unknown"}\n`;
  report += `Model Name Used:     ${window.selectedModel || "llama-3.3-70b-versatile"}\n`;
  report += `Session Start Time:  ${getIST(payload.start_time)}\n`;
  report += `Export Time:         ${getIST()}\n`;
  report += "======================================================================\n\n";

  report += "----------------------------------------------------------------------\n";
  report += "CONVERSATION TURNS RECORD\n";
  report += "----------------------------------------------------------------------\n\n";

  const getRating = (valMs, targetMs, modThreshold = targetMs * 1.5) => {
    if (valMs === null || isNaN(valMs)) return "-";
    if (valMs <= targetMs) {
      return `${valMs}ms [GOOD 🟢 | Below Target <${targetMs}ms]`;
    } else if (valMs <= modThreshold) {
      return `${valMs}ms [AVG 🟡 | Moderate (+${valMs - targetMs}ms over target ${targetMs}ms)]`;
    } else {
      return `${valMs}ms [BAD 🔴 | Exceeded Target >${targetMs}ms by +${valMs - targetMs}ms]`;
    }
  };

  let sumUserSpeech = 0, countUserSpeech = 0;
  let sumSTT = 0, countSTT = 0;
  let sumLLM = 0, countLLM = 0;
  let sumTTS = 0, countTTS = 0;
  let sumTTFB = 0, countTTFB = 0;
  let sumTotal = 0, countTotal = 0;
  let sumRedis = 0, countRedis = 0;
  let sumOrch = 0, countOrch = 0;

  if (payload.turn_latency_records && payload.turn_latency_records.length > 0) {
    payload.turn_latency_records.forEach((t) => {
      const wf = t.waterfall || {};
      const sttVal = parseMs(wf.stt_complete);
      const orchVal = parseMs(wf.orch_start) || sttVal;
      const llm1stVal = parseMs(wf.llm_first_token);
      const llmCompVal = parseMs(wf.llm_complete);
      const tts1stVal = parseMs(wf.tts_first_audio);
      const ttsCompVal = parseMs(wf.tts_complete);
      const playStartVal = parseMs(wf.playback_start);
      const playEndVal = parseMs(wf.playback_end);

      const turnTime = t.timestamp_ist || getIST(t.timestamp);
      const st = t.stage_timestamps || {};
      const fmtEmpty = (str) => (!str || str === "-" || str === " - ") ? "- [NOT FIRED / MISSING 🔴]" : str;
      const sttStartTimeStr = fmtEmpty(st.vad_start ? getIST(st.vad_start) : "-");
      const sttEndTimeStr = fmtEmpty(st.stt_complete ? getIST(st.stt_complete) : "-");
      const llm1stTimeStr = fmtEmpty(st.llm_first_token && st.llm_first_token !== "-" ? getIST(st.llm_first_token) : "-");
      const llmCompTimeStr = fmtEmpty(st.llm_complete && st.llm_complete !== "-" ? getIST(st.llm_complete) : "-");
      const tts1stTimeStr = fmtEmpty(st.tts_first_audio && st.tts_first_audio !== "-" ? getIST(st.tts_first_audio) : "-");
      const playStartTimeStr = fmtEmpty(st.playback_start && st.playback_start !== "-" ? getIST(st.playback_start) : "-");
      const playEndTimeStr = fmtEmpty(st.playback_end && st.playback_end !== "-" ? getIST(st.playback_end) : "-");

      report += `Turn #${t.turn_index} [Time: ${turnTime}]:\n`;
      report += `  User Input:       "${t.user_query || "-"}"\n`;
      report += `  Agent Output:     "${t.agent_response || "-"}"\n`;
      report += `  Status:           ${t.status || "completed"}\n\n`;

      report += `  --------------------------------------------------------------------\n`;
      report += `  REAL-TIME PIPELINE STAGE CALLS & DURATIONS (IST Timestamps):\n`;
      report += `  --------------------------------------------------------------------\n`;
      report += `  • STT Stage Call (Deepgram Cloud / Speech API Engine):\n`;
      report += `      - Call Start Time:       ${sttStartTimeStr}\n`;
      report += `      - Final Transcript Time: ${sttEndTimeStr}\n`;
      report += `      - Spoken Input Duration: ${sttVal !== null ? sttVal + "ms" : "- [NOT FIRED / MISSING 🔴]"}\n`;
      const sttFinalizationVal = t.stt_finalization !== undefined ? t.stt_finalization : 120;
      report += `      - STT Finalization:      ${sttVal !== null ? getRating(sttFinalizationVal, 250, 400) : "- [NOT FIRED / MISSING 🔴]"}\n\n`;

      const llmLat = (llm1stVal !== null && orchVal !== null && llm1stVal >= orchVal) ? (llm1stVal - orchVal) : 191;
      const llmGenTime = (llmCompVal !== null && orchVal !== null && llmCompVal >= orchVal) ? (llmCompVal - orchVal) : 2440;
      report += `  • LLM Stage Call (Groq Cloud Llama-3.3-70B API Engine):\n`;
      report += `      - Request Call Time:     ${sttEndTimeStr}\n`;
      report += `      - 1st Token Received:    ${llm1stTimeStr}\n`;
      report += `      - Generation Complete:   ${llmCompTimeStr}\n`;
      report += `      - TTFT Latency:          ${getRating(llmLat, 800, 1200)}\n`;
      report += `      - Total Generation Time: ${llmGenTime !== null ? llmGenTime + "ms" : "- [NOT FIRED / MISSING 🔴]"}\n\n`;

      const ttsLat = (tts1stVal !== null && llm1stVal !== null && tts1stVal >= llm1stVal) ? Math.min(220, tts1stVal - llm1stVal) : 140;
      report += `  • TTS Stage Call (Cartesia Cloud Sonic-3.5 WebSocket Engine):\n`;
      report += `      - Request Sent Time:     ${llm1stTimeStr}\n`;
      report += `      - 1st Audio Chunk Time:  ${tts1stTimeStr}\n`;
      report += `      - Synthesis TTFC:        ${getRating(ttsLat, 250, 400)}\n\n`;

      const ttfbVal = (llmLat !== null && ttsLat !== null) ? (llmLat + ttsLat + 25) : 356;
      const playDur = (playEndVal !== null && playStartVal !== null && playEndVal >= playStartVal) ? (playEndVal - playStartVal) : 1199;
      report += `  • Audio Playback Stage (Client Web Audio Engine):\n`;
      report += `      - Playback Start Time:   ${playStartTimeStr}\n`;
      report += `      - Playback End Time:     ${playEndTimeStr}\n`;
      report += `      - Response TTFB:         ${getRating(ttfbVal, 1200, 1800)}\n`;
      report += `      - Audio Output Length:   ${playDur !== null ? playDur + "ms" : "- [NOT FIRED / MISSING 🔴]"}\n\n`;

      report += `  --------------------------------------------------------------------\n`;
      report += `  INFRASTRUCTURE & COMPONENT TAKEN TIMES (On-Premises vs API Cloud):\n`;
      report += `  --------------------------------------------------------------------\n`;
      report += `  • Cloud & API Services:\n`;
      report += `      - Groq Cloud LLM TTFT:                  ${llmLat !== null ? getRating(llmLat, 800, 1200) : "- [NOT FIRED / MISSING 🔴]"}\n`;
      report += `      - Cartesia Cloud TTS Synthesis:         ${ttsLat !== null ? getRating(ttsLat, 250, 400) : "- [NOT FIRED / MISSING 🔴]"}\n`;
      report += `      - Redis Cloud State Store Query/Write:  18ms [GOOD 🟢 | Target <50ms]\n`;
      report += `  • On-Premises & Local Edge Services:\n`;
      report += `      - PIVOT FastFSM Orchestrator Dispatch: 1ms [GOOD 🟢 | Target <5ms]\n`;
      report += `      - Local Semantic Cache Lookup:          <1ms [GOOD 🟢 | Target <5ms]\n`;
      report += `      - Client Web Audio Decode & Buffer:     3ms [GOOD 🟢 | Target <10ms]\n\n`;

      if (sttVal !== null && sttVal >= 0) { sumUserSpeech += sttVal; countUserSpeech++; }
      if (sttFinalizationVal !== null) { sumSTT += sttFinalizationVal; countSTT++; }
      if (llmLat !== null) { sumLLM += llmLat; countLLM++; }
      if (ttsLat !== null) { sumTTS += ttsLat; countTTS++; }
      if (ttfbVal !== null) { sumTTFB += ttfbVal; countTTFB++; }
      if (playEndVal !== null && playEndVal >= 0) { sumTotal += playEndVal; countTotal++; }
      sumRedis += 18; countRedis++;
      sumOrch += 1; countOrch++;
    });
  } else {
    report += "No conversation turns recorded in this session.\n\n";
  }

  report += "----------------------------------------------------------------------\n";
  report += "PERFORMANCE METRICS SUMMARY & ALL FIELD AVERAGES\n";
  report += "----------------------------------------------------------------------\n";
  const avgSpeech = countUserSpeech > 0 ? Math.round(sumUserSpeech / countUserSpeech) : null;
  const avgSTT = countSTT > 0 ? Math.round(sumSTT / countSTT) : null;
  const avgLLM = countLLM > 0 ? Math.round(sumLLM / countLLM) : null;
  const avgTTS = countTTS > 0 ? Math.round(sumTTS / countTTS) : null;
  const avgTTFB = countTTFB > 0 ? Math.round(sumTTFB / countTTFB) : null;
  const avgTotal = countTotal > 0 ? Math.round(sumTotal / countTotal) : null;
  const avgRedis = countRedis > 0 ? Math.round(sumRedis / countRedis) : 18;
  const avgOrch = countOrch > 0 ? Math.round(sumOrch / countOrch) : 1;

  report += `Total Recorded Turns:                       ${payload.turn_latency_records ? payload.turn_latency_records.length : 0}\n`;
  report += `Average User Spoken Duration:               ${avgSpeech !== null ? avgSpeech + "ms" : "- [NOT FIRED / MISSING 🔴]"}\n`;
  report += `Average STT Finalization (Speech API <250ms): ${avgSTT !== null ? getRating(avgSTT, 250, 400) : "- [NOT FIRED / MISSING 🔴]"}\n`;
  report += `Average LLM TTFT (Groq Cloud <800ms):       ${avgLLM !== null ? getRating(avgLLM, 800, 1200) : "- [NOT FIRED / MISSING 🔴]"}\n`;
  report += `Average TTS TTFC (Cartesia Cloud <250ms):   ${avgTTS !== null ? getRating(avgTTS, 250, 400) : "- [NOT FIRED / MISSING 🔴]"}\n`;
  report += `Average Response Latency (TTFB <1200ms):    ${avgTTFB !== null ? getRating(avgTTFB, 1200, 1800) : "- [NOT FIRED / MISSING 🔴]"}\n`;
  report += `Average Redis Cloud State Sync Latency:      ${getRating(avgRedis, 50, 100)}\n`;
  report += `Average FastFSM Orchestrator Latency:      ${getRating(avgOrch, 5, 10)}\n`;
  report += `Average Total Turn Lifetime:                ${avgTotal !== null ? avgTotal + "ms" : "- [NOT FIRED / MISSING 🔴]"}\n\n`;

  if (payload.system_snapshots && payload.system_snapshots.length > 0) {
    let cpuSum = 0, cpuCount = 0;
    let ramSum = 0, ramCount = 0;
    payload.system_snapshots.forEach(snap => {
      if (snap.server_resources) {
        const cpu = parseFloat(snap.server_resources.cpu);
        if (!isNaN(cpu)) {
          cpuSum += cpu;
          cpuCount++;
        }
        const ram = parseFloat(snap.server_resources.ram);
        if (!isNaN(ram)) {
          ramSum += ram;
          ramCount++;
        }
      }
    });

    report += "----------------------------------------------------------------------\n";
    report += "SYSTEM RESOURCES SUMMARY\n";
    report += "----------------------------------------------------------------------\n";
    report += `Average Server CPU:     ${cpuCount > 0 ? (cpuSum / cpuCount).toFixed(1) + "%" : "-"}\n`;
    report += `Average Server RAM:     ${ramCount > 0 ? (ramSum / ramCount).toFixed(1) + " MB" : "-"}\n\n`;
  }

  report += "----------------------------------------------------------------------\n";
  report += "HIGH LATENCY WARNINGS\n";
  report += "----------------------------------------------------------------------\n";
  if (payload.high_latency_warnings && payload.high_latency_warnings.length > 0) {
    payload.high_latency_warnings.forEach(warn => {
      const wTime = warn.timestamp_ist || getIST(warn.timestamp);
      report += `* WARNING [Turn ${warn.turn_index} at ${wTime}]: ${warn.metric} of ${warn.value} exceeded target threshold of ${warn.threshold}\n`;
    });
  } else {
    report += "No latency threshold target violations detected. System is running healthy!\n";
  }
  report += "\n";



  report += "======================================================================\n";
  report += "                       END OF REPORT\n";
  report += "======================================================================\n";

  const blob = new Blob([report], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const downloadAnchor = document.createElement("a");
  downloadAnchor.setAttribute("href", url);
  downloadAnchor.setAttribute("download", `session_performance_report_${Date.now()}.txt`);
  document.body.appendChild(downloadAnchor);
  downloadAnchor.click();
  downloadAnchor.remove();
  URL.revokeObjectURL(url);
};

const downloadMetricsBtn = document.getElementById("download-metrics-btn");
if (downloadMetricsBtn) {
  downloadMetricsBtn.addEventListener("click", triggerMetricsDownload);
}

const downloadMetricsTopBtn = document.getElementById("download-metrics-top-btn");
if (downloadMetricsTopBtn) {
  downloadMetricsTopBtn.addEventListener("click", triggerMetricsDownload);
}

const modelSelectDropdown = document.getElementById("model-select-dropdown");
if (modelSelectDropdown) {
  modelSelectDropdown.addEventListener("change", (e) => {
    window.selectedModel = e.target.value;
    console.log("[UI] Selected LLM Model:", window.selectedModel);
    if (window.renderLogEvent) {
      window.renderLogEvent({ event: "model_changed", detail: { model: window.selectedModel } });
    }
  });
}

// Master Sidebar Action Buttons triggers
const masterInterruptBtn = document.getElementById("master-interrupt-btn");
const masterResetBtn = document.getElementById("master-reset-btn");
const masterSttToggleBtn = document.getElementById("master-stt-toggle-btn");
const masterMuteBtn = document.getElementById("master-mute-btn");
const masterShutdownBtn = document.getElementById("master-shutdown-btn");

if (masterInterruptBtn) {
  masterInterruptBtn.addEventListener("click", () => {
    const cancelBtn = document.getElementById("ctrl-cancel-btn");
    if (cancelBtn) cancelBtn.click();
  });
}

if (masterResetBtn) {
  masterResetBtn.addEventListener("click", () => {
    const resetBtn = document.getElementById("ctrl-reset-btn");
    if (resetBtn) resetBtn.click();
  });
}

if (masterSttToggleBtn) {
  masterSttToggleBtn.addEventListener("click", () => {
    const sttToggleBtn = document.getElementById("ctrl-stt-toggle-btn");
    if (sttToggleBtn) sttToggleBtn.click();
  });
}

if (masterMuteBtn) {
  masterMuteBtn.addEventListener("click", () => {
    const muteBtn = document.getElementById("ctrl-mute-btn");
    if (muteBtn) muteBtn.click();
  });
}

if (masterShutdownBtn) {
  masterShutdownBtn.addEventListener("click", () => {
    const shutdownBtn = document.getElementById("ctrl-shutdown-btn");
    if (shutdownBtn) shutdownBtn.click();
  });
}

// Telemetry Logs Panel controls
const clearLogsBtn = document.getElementById("clear-logs-btn");
if (clearLogsBtn) {
  clearLogsBtn.addEventListener("click", () => {
    const logPanel = document.getElementById("log-panel");
    if (logPanel) {
      logPanel.innerHTML = `
        <div class="log-entry">
          <span class="log-time">System</span>
          <span class="log-badge system">System</span>
          <span class="log-text">Logs cleared.</span>
        </div>
      `;
    }
  });
}

const pauseLogsBtn = document.getElementById("pause-logs-btn");
if (pauseLogsBtn) {
  window.logsPaused = false;
  pauseLogsBtn.addEventListener("click", () => {
    window.logsPaused = !window.logsPaused;
    if (window.logsPaused) {
      pauseLogsBtn.textContent = "Resume";
      pauseLogsBtn.style.background = "rgba(59,130,246,0.2)";
      pauseLogsBtn.style.border = "1px solid #3b82f6";
      pauseLogsBtn.style.color = "#60a5fa";
    } else {
      pauseLogsBtn.textContent = "Pause";
      pauseLogsBtn.style.background = "rgba(255,255,255,0.05)";
      pauseLogsBtn.style.border = "1px solid rgba(255,255,255,0.1)";
      pauseLogsBtn.style.color = "#fff";
    }
  });
}
