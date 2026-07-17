"""
stt_client.py — Phase 1 deliverable.

CORRECTED WIRING
-----------------
    deepgram-stt.out-transcript -> orchestrator.in-transcript

WHAT TO IMPLEMENT
------------------
- handle_transcript(session_id, transcript, is_final: bool): receives
  streaming partials and finals from Deepgram (via media-gateway), logs
  stt_partial / stt_final events with latency_ms, hands final transcripts
  to fsm.py to advance the turn.

LOG EVENTS
----------
- stt_partial { session_id, turn_id, text, latency_ms }
- stt_final   { session_id, turn_id, text, latency_ms }
"""

# TODO(phase-1): implement handle_transcript
