"""
Phase 8 test gate (RAG) — see docs/pivot-build-plan.md Phase 8.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- A fact seeded into the Qdrant-backed knowledge base is correctly
  retrieved (RAG_RETRIEVED logged) and cited/reflected in the LLM's reply
  for a query that requires it.

Un-skip as part of the Phase 8 prompt, once rag_client.py is implemented
and RAG_ENABLED=true in the test environment.
"""
import pytest


@pytest.mark.skip(reason="Phase 8 not yet implemented — see PHASE_PROMPTS.md")
def test_kb_seeded_fact_is_retrieved_and_grounds_reply():
    ...
