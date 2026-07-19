from common.config.settings import get_settings
from common.logging.logger import get_logger
from services.media_gateway.events import MediaEvent, publish
import time

logger = get_logger("media-gateway")

def create_room(session_id: str) -> str:
    """Consumes room token creation logic and logs the event."""
    from services.edge_auth.token_service import issue_token
    room_name = f"room-{session_id}"
    token = issue_token(session_id, room_name)
    logger.log(
        event_name="room_created",
        session_id=session_id,
        turn_id="system",
        detail={"room_name": room_name}
    )
    return token

def on_participant_track_published(session_id: str, track_kind: str):
    """Callback when a participant publishes a media track."""
    logger.log(
        event_name="track_published",
        session_id=session_id,
        turn_id="system",
        detail={"track_kind": track_kind}
    )
    logger.log(
        event_name="track_subscribed",
        session_id=session_id,
        turn_id="system",
        detail={"track_kind": track_kind}
    )

_active_relays = {}

def stop_tts_relay(session_id: str):
    """Flags the active audio stream to stop transmission instantly."""
    _active_relays[session_id] = False
    logger.log(
        event_name="tts_relay_stopped",
        session_id=session_id,
        turn_id="system",
        detail={"msg": "Media gateway stopped relaying agent audio"}
    )

def cleanup_session(session_id: str):
    """Removes session state to prevent memory leaks in multi-user concurrent scenarios."""
    _active_relays.pop(session_id, None)
    logger.log(
        event_name="session_cleaned_up",
        session_id=session_id,
        turn_id="system",
        detail={"msg": "Cleaned up media gateway session relay state"}
    )

def publish_agent_audio(session_id: str, audio_stream):
    """Streams synthesized response audio back to the client, checking for interruption flags."""
    _active_relays[session_id] = True
    for chunk in audio_stream:
        if not _active_relays.get(session_id, True):
            logger.log(
                event_name="tts_relay_aborted",
                session_id=session_id,
                turn_id="system",
                detail={"msg": "Discarded remaining audio frames in relay queue"}
            )
            break
        from common.config.voice_settings import get as vc_get
        time.sleep(vc_get("tts.mock_chunk_sleep_ms", 10) / 1000.0)

def emit_media_event(session_id: str, event_kind: str, detail: dict = None):
    """Converts local state updates into MediaEvents and publishes them."""
    import time
    ev = MediaEvent(
        session_id=session_id,
        kind=event_kind,
        ts=time.time(),
        detail=detail or {}
    )
    publish(ev)
