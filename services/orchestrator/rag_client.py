"""
rag_client.py — Phase 8 deliverable.

CORRECTED WIRING
-----------------
    orchestrator.out-kb-lookup -> knowledge-base-memory-db.in-kb-req
    knowledge-base-memory-db.out-kb-res -> orchestrator.in-kb-res

(the original uploaded JSON sourced this from out-cache-req and targeted a
generic placeholder port on the KB db instead of in-kb-req — see section 0)

FEATURE FLAG
------------
Qdrant integration behind RAG_ENABLED (common/config/settings.py).

WHAT TO IMPLEMENT
------------------
- retrieve(query) -> grounding context from the vector DB, injected into
  the LLM prompt before generation.

LOG EVENTS
----------
- rag_retrieved { session_id, turn_id, num_results, latency_ms }

RELATED
-------
- tests/phase8/test_rag_grounding.py — asserts a KB-seeded fact is
  correctly retrieved and cited in the reply.
"""

# TODO(phase-8): implement retrieve, RAG_ENABLED flag
