"""
tools.py — Phase 6 deliverable.

CORRECTED WIRING
-----------------
    task-execution-service.out-api-req -> external-apis-integration.in-api
    (the original uploaded architecture JSON had this edge sourced from the
    input port in-api-res, backwards — see docs/pivot-build-plan.md section 0)

OPEN DECISION — RESOLVE BEFORE WRITING CODE
------------------------------------------------
The PRD requires "a defined policy for interruptions mid-call" but does not
hand you the policy table. Per docs/pivot-build-plan.md section 6, this must
be an explicit decision, written into that doc's phase-6 policy table,
BEFORE implementation — not improvised while coding. Suggested starting
point per interruption type (confirm/adjust and record the final version in
the build plan doc):

    correction     -> if the tool call is cancelable, abort and restart
                       with corrected params; if not, let it finish, then
                       apply the correction to the *next* action.
    topic-change   -> if cancelable, abort; if not, let it finish silently
                       and don't surface its result if it's now irrelevant.
    clarification  -> tool call continues in the background; answer the
                       clarification first.
    stop_cancel    -> abort if at all cancelable; otherwise let it finish
                       and discard/log the result without speaking it.
    add_on         -> queue as a follow-up call after the current one
                       completes.

WHAT TO IMPLEMENT
------------------
- invoke_tool(session_id, tool_name, params) -> calls
  task-execution-service.out-api-req.
- on_interruption_during_call(session_id, interruption_type): applies the
  policy table above.

LOG EVENTS
----------
- tool_call_started      { session_id, turn_id, tool_name }
- tool_call_interrupted  { session_id, turn_id, tool_name, policy_applied }
- tool_call_completed    { session_id, turn_id, tool_name, latency_ms }

RELATED
-------
- services/task-worker/worker.py
- tests/phase6/test_tool_interrupt_policy.py — one test per policy branch above.
"""

# TODO(phase-6): confirm policy table in docs/pivot-build-plan.md, then implement
