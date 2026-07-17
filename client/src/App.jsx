/*
 * client/src/App.jsx — Phase 3 deliverable (promotion from phase1_minimal_harness).
 *
 * PURPOSE
 * -------
 * The real PRD client: React + WebRTC + local Silero VAD, replacing the
 * Phase 1 bare test page once client-side VAD ducking is needed for the
 * barge-in kill switch.
 *
 * WHAT TO IMPLEMENT (Phase 3)
 * -----------------------------
 * 1. Port the Phase 1 harness's room-join / audio-playback logic into React
 *    components (do not throw it away — it's the proven-working baseline).
 * 2. Mount vad/SileroVAD.js against the local mic stream; on sustained
 *    speech, locally "duck" (attenuate) playback of the agent's audio
 *    immediately, client-side, before any server round trip — this is what
 *    makes barge-in feel instant even though the real kill signal
 *    (orchestrator.out-tts-ctrl -> cartesia-tts.in-tts-ctrl) has network
 *    latency.
 * 3. On a false positive (VAD triggered but no real interruption confirmed
 *    by the server), smoothly resume playback rather than an abrupt jump —
 *    this is an explicit PRD non-functional requirement.
 * 4. Visual state: show the agent's current state (speaking / listening /
 *    thinking / interrupted) so the "3+ natural interruptions" demo is
 *    legible to an audience, not just to the person on the mic.
 *
 * WHAT TO IMPLEMENT LATER (do not build here yet)
 * --------------------------------------------------
 * - Phase 4+: any UI reflecting interruption *type* (correction vs
 *   topic-change etc.) — optional polish, not required for the core loop.
 *
 * RELATED
 * -------
 * - client/src/vad/SileroVAD.js
 * - services/orchestrator/barge_in.py (Phase 3 server-side counterpart)
 * - tests/phase3/test_barge_in_latency.py
 */

// TODO(phase-3): implement React app shell, port Phase 1 harness logic in
