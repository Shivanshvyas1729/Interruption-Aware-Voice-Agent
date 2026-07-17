from common.config.settings import get_settings
from common.logging.logger import get_logger
from services.media_gateway.events import MediaEvent, publish

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

def publish_agent_audio(session_id: str, audio_stream):
    """Streams synthesized response audio back to the client."""
    pass

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
