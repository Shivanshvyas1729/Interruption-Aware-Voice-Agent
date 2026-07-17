"""
Phase 9 test gate (concurrency) — see docs/pivot-build-plan.md Phase 9.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- 2-3 simulated concurrent sessions (via the load-testing-eval service) run
  without cross-session state leakage (session A never sees session B's
  transcript/context via state_store.py).
- Latency budgets (barge-in kill <300ms p95, turnaround <1.5s p95) still
  hold under this concurrent load, not just in isolation.

Un-skip as part of the Phase 9 prompt.
"""
import pytest


@pytest.mark.skip(reason="Phase 9 not yet implemented — see PHASE_PROMPTS.md")
def test_concurrent_sessions_no_leakage_and_latency_holds():
    ...
