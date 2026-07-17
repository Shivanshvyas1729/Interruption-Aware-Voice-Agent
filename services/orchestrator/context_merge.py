"""
context_merge.py — Phase 5 deliverable.

PURPOSE
-------
Given (a) exactly what the agent was saying when cut off (from
tts_client.on_word_timestamp) and (b) the interruption's classified type
(from interruption_classifier.classify), decide what happens next and build
the merged context for the next LLM call.

RESOLUTION STRATEGY PER TYPE (distinct behavior — do not collapse to one
generic "pivot" path; this was explicitly called out as a gap in existing
voice assistants in the PRD problem statement)
--------------------------------------------------------------------------
    correction     -> merge the correction into context, regenerate the
                       response from the corrected point forward.
    topic-change   -> abandon the current response entirely, start fresh.
    clarification  -> pause current response, answer the clarification,
                       THEN resume the original (unspoken remainder).
    stop_cancel    -> abandon, no resume, no regeneration.
    add_on         -> finish or fold the addition into the current
                       response, continue naturally (no restart).

WHAT TO IMPLEMENT
------------------
- resolve(session_id, spoken_words, unspoken_words, interruption_type)
  -> { strategy, merged_context } consumed by fsm.py to decide the next
     state transition and by llm_client.py to build the next prompt.

LOG EVENTS
----------
- interruption_resolved { session_id, turn_id, strategy, merged_context_summary }

RELATED
-------
- tests/phase5/test_context_merge.py — one assertion per type above.
"""

# TODO(phase-5): implement resolve() for all 5 interruption types
