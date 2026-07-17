"""
Phase 7 test gate (semantic cache) — see docs/pivot-build-plan.md Phase 7.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- A repeated (semantically similar) query hits the cache (CACHE_HIT logged)
  and returns measurably faster than the original cache-miss request.

Un-skip as part of the Phase 7 prompt, once cache_client.py is implemented.
"""
import pytest


@pytest.mark.skip(reason="Phase 7 not yet implemented — see PHASE_PROMPTS.md")
def test_repeated_query_is_faster_via_cache():
    ...
