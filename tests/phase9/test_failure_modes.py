"""
Phase 9 test gate (failure modes) — see docs/pivot-build-plan.md Phase 9.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT one case per row of the PRD's
failure-mode table, each producing its DOCUMENTED behavior (not a crash):
- STT drop mid-utterance
- double interruption (user interrupts again before the first is resolved)
- both primary AND fallback LLM unreachable simultaneously
- VAD false positive with smooth resume (no abrupt audio jump)
- (add any further rows from the PRD's failure-mode table here as they're
  finalized — this docstring should be kept in 1:1 sync with that table)

Un-skip as part of the Phase 9 prompt, once each failure-mode handler is
implemented across fsm.py / barge_in.py / failover.py as applicable.
"""
import pytest


@pytest.mark.skip(reason="Phase 9 not yet implemented — see PHASE_PROMPTS.md")
def test_each_failure_mode_produces_documented_behavior():
    ...
