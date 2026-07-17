"""
Phase 6 test gate — see docs/pivot-build-plan.md Phase 6.

PRECONDITION: the mid-call interruption policy table in
services/orchestrator/tools.py must be CONFIRMED and copied into
docs/pivot-build-plan.md's "Open Decisions" section before this test is
written for real — it's a decision, not something to improvise while
writing the test.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT, for EACH interruption type,
that an interruption injected mid-tool-call produces the policy-table's
documented behavior (abort-and-restart, finish-silently, queue-as-follow-up,
etc.) — not just "doesn't crash".

Un-skip as part of the Phase 6 prompt, once tools.py and
services/task-worker/worker.py are implemented and the policy table is final.
"""
import pytest


@pytest.mark.skip(reason="Phase 6 not yet implemented — see PHASE_PROMPTS.md")
def test_tool_call_interruption_follows_policy_table():
    ...
