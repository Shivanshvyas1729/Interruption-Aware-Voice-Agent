"""
failover.py — Phase 7 deliverable.

CORRECTED WIRING NOTE
-----------------------
The original uploaded architecture JSON tried to model primary/fallback LLM
routing as two static edges (one of which stole the other's port). In the
corrected flow this is a PROGRAMMATIC decision made here, not two parallel
static wires: orchestrator always calls out-llm-req, and the target
(primary vs fallback) is decided by this module. Both return through the
same in-llm-stream channel.

WHAT TO IMPLEMENT
------------------
- call_with_failover(messages) -> tries llm_client.call_primary(messages);
  on failure/timeout, falls back to OpenAI, using a SHARED persona/system-
  prompt module so the fallback's tone is indistinguishable from the
  primary's. The failover must be silent — no "switching models" leakage
  into the transcript or the user-facing conversation.

LOG EVENTS
----------
- llm_failover_triggered { session_id, turn_id, reason }
- llm_complete { ..., provider: "groq" | "openai" }   (extends the Phase 1 event)

RELATED
-------
- tests/phase7/test_failover.py — asserts failover happens, persona holds,
  and no failover leakage appears in the transcript.
"""

# TODO(phase-7): implement call_with_failover + shared persona module
