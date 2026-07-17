"""
interruption_classifier.py — Phase 4 deliverable.

PURPOSE
-------
Distinguish real interruptions from backchanneling, then classify real
interruptions into the PRD's 5 types, each with a DISTINCT resolution
strategy (not one generic pivot).

WHAT TO IMPLEMENT
------------------
1. Backchannel filter: require 200ms of sustained speech (per PRD) before
   treating audio-during-agent-speech as a real interruption at all. Short
   "mm-hm"/"yeah" should be filtered here, upstream of classification.
2. classify(transcript_fragment, context) -> one of:
     - correction     ("no, I meant...", "actually...")
     - topic-change    (unrelated new topic)
     - clarification   (question about what the agent just said)
     - stop_cancel     ("stop", "never mind", "forget it")
     - add_on          (extends/adds to the current request without
                         invalidating what's already been said)
   Rule-based first pass is fine; can be LLM-assisted for ambiguous cases.
3. Log confidence alongside the classification — low-confidence cases are
   exactly where Phase 5's resolution strategy needs to be conservative.

LOG EVENTS
----------
- interruption_classified { session_id, turn_id, type, confidence }

EVAL TARGET
-----------
docs/pivot-build-plan.md: >=85% accuracy on the PRD's 20 scripted
interruption scenarios. This becomes a standing regression eval — re-run it
every later phase, not just once here.

RELATED
-------
- tests/phase4/test_classification_eval.py
- services/orchestrator/context_merge.py (Phase 5 — acts on this classification)
"""

# TODO(phase-4): implement backchannel filter + classify()
