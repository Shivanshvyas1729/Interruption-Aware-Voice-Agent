"""
Phase 8 test gate (regression check) — see docs/pivot-build-plan.md Phase 8.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- Re-running Phase 3's barge-in latency scenario and Phase 1's single-turn
  turnaround scenario, WITH guardrails + RAG now in the request path, shows
  no regression against the numbers captured before Phase 8 landed.
- Each of ENKRYPT_ENABLED, RAG_ENABLED, MASTRA_ENABLED can be individually
  flipped to false and the core loop (Phase 1-7 tests) still passes —
  proving the feature-flag isolation required by ground rule #11.

Un-skip as part of the Phase 8 prompt, after guardrails_client.py and
rag_client.py are implemented.
"""
import pytest


@pytest.mark.skip(reason="Phase 8 not yet implemented — see PHASE_PROMPTS.md")
def test_sponsor_tech_additions_do_not_regress_latency_or_break_when_flagged_off():
    ...
