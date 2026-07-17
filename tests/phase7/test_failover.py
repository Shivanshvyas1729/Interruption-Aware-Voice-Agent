"""
Phase 7 test gate (LLM failover) — see docs/pivot-build-plan.md Phase 7.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- With the primary (Groq) made unreachable via fault injection, the
  fallback (OpenAI) is used instead (LLM_FAILOVER_TRIGGERED logged).
- The fallback's output still passes a persona-consistency check against
  the shared persona module.
- No failover leakage appears in the user-facing transcript (no
  "switching models" text, no visible seam).

Un-skip as part of the Phase 7 prompt, once failover.py is implemented.
"""
import pytest


@pytest.mark.skip(reason="Phase 7 not yet implemented — see PHASE_PROMPTS.md")
def test_silent_failover_to_openai_on_primary_failure():
    ...
