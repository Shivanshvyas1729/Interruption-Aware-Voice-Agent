"""
Phase 3 test gate — see docs/pivot-build-plan.md Phase 3.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- With TTS mid-stream, injecting simulated sustained user speech triggers
  BARGE_IN_DETECTED -> TTS_KILL_SIGNAL_SENT -> TTS_STOPPED, in order.
- latency_ms from BARGE_IN_DETECTED to TTS_STOPPED is captured and logged.
- Start asserting this against the PRD target of <300ms p95 from THIS
  phase onward (ground rule #10 — don't wait until eval week to check it).
- The literal fix from the architecture audit is exercised here:
  orchestrator.out-tts-ctrl -> cartesia-tts.in-tts-ctrl must actually fire
  and actually stop audio (this edge did not exist at all in the original
  uploaded architecture JSON — see docs/pivot-build-plan.md section 0).

Un-skip as part of the Phase 3 prompt, once services/orchestrator/
barge_in.py and tts_client.py's kill() are implemented, and the client has
been promoted to client/src (React + Silero VAD).
"""
import pytest


@pytest.mark.skip(reason="Phase 3 not yet implemented — see PHASE_PROMPTS.md")
def test_barge_in_stops_tts_within_latency_budget():
    ...
