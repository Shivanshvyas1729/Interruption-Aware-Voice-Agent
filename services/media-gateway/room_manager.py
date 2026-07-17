"""
room_manager.py — Phase 1 deliverable (data plane, LiveKit glue).

CORRECTED PORT WIRING THIS MODULE IMPLEMENTS
-----------------------------------------------
(see docs/pivot-build-plan.md section 0 — the ORIGINAL uploaded architecture
JSON had every one of these edges wrong; do not copy its literal wiring)

    web-client.out-audio      -> livekit.in-audio-client   (client mic in)
    livekit.out-audio-client  -> web-client.in-audio        (agent audio out to client)
    livekit.out-audio-stt     -> deepgram-stt.in-audio      (client audio to STT)
    cartesia-tts.out-audio    -> livekit.in-audio-tts       (TTS audio in)
    livekit.out-events        -> orchestrator.in-media-events

WHAT TO IMPLEMENT (Phase 1)
------------------------------
1. create_room(session_id) -> room token, using LIVEKIT_URL / API_KEY / SECRET
   from common.config.settings.
2. on_participant_track_published(track): if it's the client mic, subscribe
   and forward the audio stream to Deepgram STT (see services/orchestrator/
   stt_client.py for where the transcript ends up).
3. publish_agent_audio(session_id, audio_stream): takes Cartesia's TTS
   output and publishes it back into the room so the client hears it.
4. emit_media_event(session_id, event): forwards room-level events (join,
   leave, track state changes) to the orchestrator's in-media-events —
   this becomes load-bearing in Phase 3+ for detecting real vs. stale
   audio streams during barge-in.

PHASE 3 ADDITION (do not implement yet, noted for context)
---------------------------------------------------------------
- Barge-in requires this module to actually STOP relaying TTS audio the
  moment orchestrator.out-tts-ctrl fires, not just stop generating it
  upstream. Track that requirement here so it isn't missed.

LOG EVENTS THIS MODULE IS RESPONSIBLE FOR
--------------------------------------------
- room_created { session_id }
- track_published { session_id, track_kind }
- track_subscribed { session_id, track_kind }

RELATED
-------
- tests/phase1/test_single_turn.py
"""

# TODO(phase-1): implement create_room, on_participant_track_published,
#                publish_agent_audio, emit_media_event
