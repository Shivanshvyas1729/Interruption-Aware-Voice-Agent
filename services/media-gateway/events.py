"""
events.py — Phase 1 (base), load-bearing from Phase 3 onward.

PURPOSE
-------
Typed wrapper around livekit.out-events -> orchestrator.in-media-events.
Kept separate from room_manager.py so the event *shape* (what a media event
looks like) is defined once and reused by every phase that needs to react
to room-level state (barge-in in Phase 3, failure-mode handling in Phase 9).

WHAT TO IMPLEMENT (Phase 1)
------------------------------
- MediaEvent dataclass/schema: { session_id, kind, ts, detail }
- publish(event: MediaEvent) -> sends to orchestrator's in-media-events
  handler (see services/orchestrator/fsm.py).

PHASE 9 ADDITION (noted for context, not implemented yet)
---------------------------------------------------------------
- STT-drop and other failure-mode events from the PRD's failure-mode table
  should be modeled as MediaEvent kinds here, so orchestrator failure
  handling (Phase 9) has one consistent event shape to react to.
"""

# TODO(phase-1): implement MediaEvent, publish()
