"""
client.py — Phase 6 deliverable.

CORRECTED WIRING
-----------------
    task-execution-service.out-api-req -> external-apis-integration.in-api
    external-apis-integration.out -> task-execution-service (Job Res)

(the original uploaded architecture JSON sourced this edge from
task-execution-service.in-api-res, an input port used backwards — see
docs/pivot-build-plan.md section 0)

WHAT TO IMPLEMENT
------------------
- handle_api_request(tool_name, params) -> result: a thin adapter layer
  over whatever real third-party APIs the demo actually needs (REST/GraphQL
  per the architecture's tech tags). For the hackathon/demo scope, this can
  wrap 1-2 mock or sandbox integrations rather than real production
  banking/CRM systems — note which in this file once decided.

LOG EVENTS
----------
- external_api_called    { session_id, tool_name, latency_ms }
- external_api_failed    { session_id, tool_name, reason }

RELATED
-------
- services/task-worker/worker.py — the caller of this module.
- services/orchestrator/tools.py — owns the interruption policy around
  calls made here.
- tests/phase6/test_tool_interrupt_policy.py
"""

# TODO(phase-6): implement handle_api_request; decide + document which
#                real/mock external APIs back the demo
