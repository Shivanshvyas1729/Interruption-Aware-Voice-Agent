"""
Phase 1 test gate — see docs/pivot-build-plan.md Phase 1.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT (using a FIXTURE WAV, not a live
mic — ground rule #9):
- A fixture audio clip ("What's the weather like on Mars?") produces a
  non-empty transcript via the STT stub.
- An LLM reply is generated (primary/Groq only, no memory/cache/guardrails
  yet).
- TTS returns non-empty audio bytes.
- The full expected log sequence fires in order: STT_PARTIAL, STT_FINAL,
  LLM_FIRST_TOKEN, LLM_COMPLETE, TTS_FIRST_AUDIO, TTS_COMPLETE, with
  TURN_TOTAL_MS recorded (no threshold assertion yet — just captured).

Un-skip as part of the Phase 1 prompt, once services/orchestrator/{fsm,
stt_client,llm_client,tts_client}.py and services/media-gateway/
room_manager.py have real implementations.
"""
import pytest


@pytest.mark.skip(reason="Phase 1 not yet implemented — see PHASE_PROMPTS.md")
def test_single_turn_end_to_end_from_fixture():
    ...
