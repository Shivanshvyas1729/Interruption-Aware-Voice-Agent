"""
Phase 2 test gate — see docs/pivot-build-plan.md Phase 2.

WHEN IMPLEMENTED, THIS TEST MUST ASSERT:
- A scripted 3-turn fixture conversation, where turn 2/3 refer back to
  content established in turn 1 (e.g. pronoun resolution).
- The LLM request payload sent on turns 2 and 3 actually contains turn-1
  content — verified by reading it back directly from Redis in the test
  (services/orchestrator/state_store.py), not just by trusting the reply.
- Conversation state survives a simulated orchestrator process restart.

Un-skip as part of the Phase 2 prompt, once state_store.py is implemented
and fsm.py/llm_client.py are wired to read/write it every turn.
"""
import pytest


@pytest.mark.skip(reason="Phase 2 not yet implemented — see PHASE_PROMPTS.md")
def test_conversation_state_persists_across_turns_and_restart():
    ...
