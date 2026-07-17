"""
cache_client.py — Phase 7 deliverable (semantic cache).

CORRECTED WIRING
-----------------
    orchestrator.out-cache-req -> llm-semantic-cache.in-cache-req
    llm-semantic-cache.out-cache-res -> orchestrator.in-cache-res

(the original uploaded architecture JSON sourced the request edge from
in-safety-res, an input port, backwards — see section 0 of the build plan)

WHAT TO IMPLEMENT
------------------
- lookup(query) -> cached response if a semantically similar query was
  answered recently, else None. Checked BEFORE calling failover.py.
- store(query, response): cache a fresh response for future hits.

LOG EVENTS
----------
- cache_hit  { session_id, turn_id, latency_ms }
- cache_miss { session_id, turn_id }

RELATED
-------
- tests/phase7/test_cache_hit.py
"""

# TODO(phase-7): implement lookup, store
