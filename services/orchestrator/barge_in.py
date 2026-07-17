"""
barge_in.py — Phase 3 deliverable.

PURPOSE
-------
Server-side counterpart to client/src/vad/SileroVAD.js. Decides, from
in-media-events + in-transcript signals, whether a sustained interruption
is real, and if so fires tts_client.kill().

WHAT TO IMPLEMENT (Phase 3)
------------------------------
- on_media_event(session_id, event): watches for sustained speech during
  an active `speaking` state.
- trigger_kill(session_id): calls tts_client.kill(), transitions fsm.py to
  `interrupted`, logs barge_in_detected -> tts_kill_signal_sent ->
  tts_stopped with latency_ms between each.

NOTE ON SCOPE
-------------
Phase 3 only needs "is this a real interruption, yes/no" — ANY sustained
interruption just stops TTS immediately, matching what existing voice
assistants already do per the PRD's problem statement. Phase 4 is what adds
the 200ms backchannel threshold and the 5-type classification on top of
this. Don't pull Phase 4 scope in early.

LOG EVENTS
----------
- barge_in_detected { session_id, turn_id }
  (see tts_client.py for tts_kill_signal_sent / tts_stopped)

TARGET
------
docs/pivot-build-plan.md non-functional target: barge-in kill latency
(barge_in_detected -> tts_stopped) < 300ms p95. Start measuring this in
Phase 3, don't wait until eval week.

RELATED
-------
- tests/phase3/test_barge_in_latency.py
"""

# TODO(phase-3): implement on_media_event, trigger_kill
