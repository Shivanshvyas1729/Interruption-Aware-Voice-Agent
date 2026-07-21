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
  const energyBar = document.getElementById("mic-energy-bar");
  if (energyBar) {
    energyBar.style.width = "0%";
  }
};

// Start Mic tracker automatically
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
    console.log("[Mic] Microphone access granted");
  })
  .catch(err => {
    console.warn("[Mic] Microphone analysis initialization bypassed:", err.message);
  });

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
    const rate = parseFloat(speechRateSlider.value).toFixed(1);
    speechRateVal.textContent = `${rate}x`;
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

// Default to LLM group active for clean focus
window.showGroup("grp-llm");

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

    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(settingsPayload, null, 2));
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `agent_settings_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  });
}

const downloadMetricsBtn = document.getElementById("download-metrics-btn");
if (downloadMetricsBtn) {
  downloadMetricsBtn.addEventListener("click", () => {
    const metricsPayload = {
      export_timestamp: new Date().toISOString(),
      session_id: window.sessionId || "unknown",
      session_summary: window.sessionMetrics,
      waterfall_metrics: {
        vad_start: (document.getElementById("wf-vad-start") || {}).textContent || "-",
        stt_complete: (document.getElementById("wf-stt-complete") || {}).textContent || "-",
        orch_start: (document.getElementById("wf-orch-start") || {}).textContent || "-",
        llm_first_token: (document.getElementById("wf-llm-first-token") || {}).textContent || "-",
        llm_complete: (document.getElementById("wf-llm-complete") || {}).textContent || "-",
        tts_first_audio: (document.getElementById("wf-tts-first-audio") || {}).textContent || "-",
        tts_complete: (document.getElementById("wf-tts-complete") || {}).textContent || "-",
        playback_start: (document.getElementById("wf-playback-start") || {}).textContent || "-",
        playback_end: (document.getElementById("wf-playback-end") || {}).textContent || "-"
      }
    };

    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(metricsPayload, null, 2));
    const downloadAnchor = document.createElement("a");
    downloadAnchor.setAttribute("href", dataStr);
    downloadAnchor.setAttribute("download", `telemetry_metrics_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
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
