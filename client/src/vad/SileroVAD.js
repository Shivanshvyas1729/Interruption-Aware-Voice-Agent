/*
 * client/src/vad/SileroVAD.js — Phase 3 deliverable.
 *
 * PURPOSE
 * -------
 * Local (client-side, in-browser) voice activity detection using Silero VAD,
 * per the PRD's "Client-side local VAD ducking with smooth resume on false
 * positives" requirement.
 *
 * WHAT TO IMPLEMENT
 * ------------------
 * - loadModel(): load the Silero VAD model (onnxruntime-web or equivalent).
 * - onAudioFrame(frame) -> { isSpeech, confidence }: per-frame inference.
 * - Sustained-speech gate: only fire a "duck" event after speech persists
 *   for the PRD's 200ms threshold — this is what separates a real
 *   interruption from a stray cough/backchannel at the CLIENT layer.
 *   NOTE: the definitive classification (backchannel vs real interruption)
 *   still happens server-side in Phase 4 (services/orchestrator/barge_in.py
 *   -> interruption_classifier.py); this client-side gate is a fast local
 *   heuristic to duck audio immediately, not the final decision.
 * - emit('duck') / emit('resume'): events consumed by App.jsx.
 *
 * LOG EVENTS THIS MODULE IS RESPONSIBLE FOR (client -> server, batched)
 * ------------------------------------------------------------------------
 * - vad_local_duck   { ts, confidence }
 *
 * RELATED
 * -------
 * - docs/pivot-build-plan.md Phase 3 test: tests/phase3/test_barge_in_latency.py
 */

// TODO(phase-3): implement loadModel, onAudioFrame, sustained-speech gate
