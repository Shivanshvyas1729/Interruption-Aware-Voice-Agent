"""
llm_client.py — Phase 1 (primary only), extended Phase 7 (failover moved to
failover.py, this file keeps the raw per-provider call).

CORRECTED WIRING
-----------------
    orchestrator.out-llm-req -> primary-llm.in-llm-req
    primary-llm.out-llm-stream -> orchestrator.in-llm-stream

WHAT TO IMPLEMENT (Phase 1)
------------------------------
- call_primary(messages) -> streaming response from Groq. Single canned
  system prompt for now — no memory (Phase 2), no cache (Phase 7), no
  guardrails (Phase 8).

PHASE 7 NOTE
------------
- Do NOT implement fallback routing here — that decision logic (when to
  fail over, how to keep persona consistent) belongs in failover.py so this
  file stays a thin per-provider client.

LOG EVENTS
----------
- llm_first_token { session_id, turn_id, latency_ms }
- llm_complete     { session_id, turn_id, latency_ms, provider }
"""

# TODO(phase-1): implement call_primary
