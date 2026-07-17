"""
state_store.py — Phase 2 deliverable.

CORRECTED WIRING
-----------------
    orchestrator.out-state-update -> app-state-store-db (Redis) .in
    app-state-store-db (Redis) .out -> orchestrator.in-state-update

WHAT TO IMPLEMENT
------------------
- save_turn(session_id, turn_id, role, content): append to the session's
  turn history in Redis.
- load_history(session_id) -> list[turn]: used by llm_client.py to build the
  multi-turn prompt (Phase 2 requirement: conversation state must survive
  an orchestrator process restart, so it lives in Redis, not memory).

RELATED
-------
- tests/phase2/test_multiturn.py — asserts turn-1 content is actually
  present in Redis and pulled into turn-2/3's LLM request payload.
"""

# TODO(phase-2): implement save_turn, load_history
