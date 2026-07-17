"""
Phase 5 test gate — see docs/pivot-build-plan.md Phase 5.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT, for EACH of the 5 interruption
types, that context_merge.resolve() produces the documented strategy AND
the resulting merged context handed to the next LLM call is correct:
- correction:    corrected fact is present; un-spoken original remainder
                  is NOT duplicated alongside it.
- topic-change:  current response fully abandoned; no leftover context
                  from the abandoned response leaks into the new one.
- clarification: clarification is answered first; the original unspoken
                  remainder is still present afterward, unchanged, for resume.
- stop_cancel:   nothing resumes; no regeneration is triggered.
- add_on:        addition is folded in without restarting the response
                  from scratch.

Un-skip as part of the Phase 5 prompt, once context_merge.py and
tts_client.on_word_timestamp are implemented.
"""
import pytest


@pytest.mark.skip(reason="Phase 5 not yet implemented — see PHASE_PROMPTS.md")
def test_resolution_strategy_per_interruption_type():
    ...
