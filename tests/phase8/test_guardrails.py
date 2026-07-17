"""
Phase 8 test gate (guardrails) — see docs/pivot-build-plan.md Phase 8.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- An unsafe-input fixture is blocked/filtered before reaching the LLM
  (GUARDRAIL_BLOCKED logged with direction="input").
- An unsafe-output fixture (simulated LLM response) is blocked before
  reaching TTS (direction="output").
- The check works whether ENKRYPT_ENABLED is true or false (i.e. there's a
  non-Enkrypt fallback path, or the test explicitly requires the flag on —
  decide and document which, then assert it).

Un-skip as part of the Phase 8 prompt, once guardrails_client.py is implemented.
"""
import pytest


@pytest.mark.skip(reason="Phase 8 not yet implemented — see PHASE_PROMPTS.md")
def test_unsafe_input_and_output_are_blocked():
    ...
