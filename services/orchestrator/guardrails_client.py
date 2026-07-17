"""
guardrails_client.py — Phase 8 deliverable.

CORRECTED WIRING
-----------------
    orchestrator.out-safety-req -> guardrails-service.in-safety-check
    guardrails-service.out-safety-res -> orchestrator.in-safety-res

(this was one of the few edges in the original uploaded JSON that was
directionally correct as-is on the request side; the response side
targeted in-media-events instead of in-safety-res — see section 0)

FEATURE FLAG
------------
Enkrypt integration behind ENKRYPT_ENABLED (common/config/settings.py) per
ground rule #11 — must be independently disable-able without breaking the
core loop, in case it destabilizes something close to demo day.

WHAT TO IMPLEMENT
------------------
- check_input(session_id, text) -> safety verdict, before it reaches the LLM.
- check_output(session_id, text) -> safety verdict, before it reaches TTS.

LOG EVENTS
----------
- guardrail_blocked { session_id, turn_id, direction: "input"|"output", reason }

RELATED
-------
- tests/phase8/test_guardrails.py
"""

# TODO(phase-8): implement check_input, check_output, ENKRYPT_ENABLED flag
