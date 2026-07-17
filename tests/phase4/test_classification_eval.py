"""
Phase 4 test gate — see docs/pivot-build-plan.md Phase 4.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- The PRD's 20 scripted interruption scenarios are run through
  interruption_classifier.classify(), producing >=85% accuracy against
  their labeled expected type (correction / topic-change / clarification /
  stop_cancel / add_on).
- A per-scenario pass/fail table is logged.
- Backchannel fixtures ("mm-hm", "yeah" under 200ms) are correctly filtered
  and do NOT trigger a false barge-in.

This becomes a STANDING regression eval — re-run (not just re-passed once)
in every later phase's regression suite to catch classification-quality
regressions introduced by unrelated changes.

Un-skip as part of the Phase 4 prompt, once interruption_classifier.py is
implemented and the 20 scenario fixtures exist under tests/phase4/fixtures/.
"""
import pytest


@pytest.mark.skip(reason="Phase 4 not yet implemented — see PHASE_PROMPTS.md")
def test_interruption_classification_accuracy_20_scenarios():
    ...


@pytest.mark.skip(reason="Phase 4 not yet implemented — see PHASE_PROMPTS.md")
def test_backchannel_does_not_trigger_barge_in():
    ...
