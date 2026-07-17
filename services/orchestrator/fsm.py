"""
fsm.py — orchestrator control-plane state machine.

Grows across nearly every phase; this file's docstring is a map of exactly
which phase adds which state/transition so it doesn't turn into an
unreadable pile later.

Phase 1  : states {idle, listening, thinking, speaking}. On in-transcript,
           call llm_client directly (no cache/guardrails/memory yet), then
           tts_client. Single-turn only.
Phase 2  : add state_store.py read/write around every transition so
           conversation history survives across turns and process restarts.
Phase 3  : add {interrupted} state. On barge_in.py signaling a sustained
           interruption, transition speaking -> interrupted, fire
           out-tts-ctrl kill signal.
Phase 4  : interrupted state gains a sub-classification step
           (interruption_classifier.py) before deciding what happens next.
Phase 5  : context_merge.py determines the transition out of `interrupted`
           — back to thinking (resume/pivot) or back to idle (abandon).
Phase 6  : add {calling_tool} state with the mid-call interruption policy
           table (see tools.py and docs/pivot-build-plan.md "Open Decisions").
Phase 7  : thinking state gains silent primary->fallback LLM failover
           (failover.py) and a cache-check sub-step (cache_client.py)
           before hitting the LLM at all.
Phase 8  : thinking state gains guardrails_client.py (input/output safety
           check) and rag_client.py (KB grounding) sub-steps, both
           feature-flagged.
Phase 9  : every transition gets wrapped with the failure-mode handling
           from the PRD's failure-mode table (STT drop, double
           interruption, both LLMs down, VAD false positive, ...).

LOG EVENTS THIS MODULE IS RESPONSIBLE FOR (cumulative across phases)
------------------------------------------------------------------------
- turn_started / turn_total_ms   (Phase 1)
- state_transition { from, to }  (Phase 1, useful from day one for debugging)
"""

# TODO(phase-1): implement the Phase 1 subset of the state machine described above
