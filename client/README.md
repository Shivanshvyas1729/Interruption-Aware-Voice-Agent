# client/

Two generations of client live here, on purpose (see docs/pivot-build-plan.md,
Phase 1's logged deviation from the PRD):

- `phase1_minimal_harness/` — a bare HTML/JS LiveKit test page. Mic in,
  speaker out, NO VAD, NO interruption handling. Its only job is to prove
  the audio pipeline (client -> LiveKit -> STT -> LLM -> TTS -> client)
  works before any UI complexity is added.

- `src/` — the real PRD client: React + WebRTC + local Silero VAD. Left
  empty/stubbed until Phase 3, when client-side VAD ducking is actually
  needed for the barge-in kill switch. Do NOT build this out early — it
  would hide whether the pipeline itself works behind UI work.
