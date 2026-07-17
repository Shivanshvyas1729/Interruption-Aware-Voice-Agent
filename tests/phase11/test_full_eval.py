"""
Phase 11 test gate (final readiness) — see docs/pivot-build-plan.md Phase 11.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- The full 20-scenario interruption eval (Phase 4's standing eval) still
  meets >=85% accuracy.
- Final latency report meets BOTH PRD non-functional targets: barge-in
  kill latency <300ms p95, end-to-end turnaround <1.5s p95 — measured
  under the same concurrent-session conditions as Phase 9, not in isolation.
- The complete `pytest tests/` regression suite (phases 0-11) is green
  with ZERO remaining @pytest.mark.skip markers — every phase's test has
  been un-skipped and actually implemented by this point.

This is the final gate before the demo-day script is rehearsed against the
real system.
"""
import pytest


@pytest.mark.skip(reason="Phase 11 not yet implemented — see PHASE_PROMPTS.md")
def test_final_eval_meets_both_nonfunctional_targets():
    ...
