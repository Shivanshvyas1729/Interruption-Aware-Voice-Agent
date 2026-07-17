"""
tts_client.py — Phase 1 (audio out), Phase 3 (kill signal), Phase 5 (word timestamps).

CORRECTED WIRING
-----------------
    orchestrator.out-tts-text -> cartesia-tts.in-tts-text     (Phase 1)
    orchestrator.out-tts-ctrl -> cartesia-tts.in-tts-ctrl     (Phase 3 — THE
        edge that was missing entirely from the original uploaded
        architecture JSON; see docs/pivot-build-plan.md section 0)
    cartesia-tts.out-word-ts  -> orchestrator.in-word-ts      (Phase 5)

WHAT TO IMPLEMENT (Phase 1)
------------------------------
- speak(session_id, text) -> streams audio to media-gateway for publishing.

WHAT TO IMPLEMENT (Phase 3)
------------------------------
- kill(session_id): sends the out-tts-ctrl stop signal. This is the actual
  fix for the audit finding — build this before anything else in Phase 3.

WHAT TO IMPLEMENT (Phase 5)
------------------------------
- on_word_timestamp(session_id, word, ts): tracks exactly which words were
  spoken vs. unspoken at kill time, feeding context_merge.py.

LOG EVENTS
----------
- tts_first_audio      { session_id, turn_id, latency_ms }           (Phase 1)
- tts_complete          { session_id, turn_id, latency_ms }           (Phase 1)
- tts_kill_signal_sent  { session_id, turn_id, latency_ms }           (Phase 3)
- tts_stopped           { session_id, turn_id, latency_ms }           (Phase 3)
"""

# TODO(phase-1): implement speak
# TODO(phase-3): implement kill
# TODO(phase-5): implement on_word_timestamp
