from livekit.api import AccessToken, VideoGrants
from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger("token-service")

def issue_token(session_id: str, room_name: str) -> str:
    """Generate a signed LiveKit room join token for the client."""
    settings = get_settings()
    
    # Reads settings. In Phase 10 this will route via secrets_manager
    api_key = settings.livekit_api_key
    api_secret = settings.livekit_api_secret
    
    if not api_key or not api_secret:
        # Fallback to mock key signature if keys are empty or dummy for offline test validation
        api_key = api_key or "mock_livekit_key"
        api_secret = api_secret or "mock_livekit_secret"
        
    token = (
        AccessToken(api_key, api_secret)
        .with_identity(session_id)
        .with_name(session_id)
        .with_grants(VideoGrants(room_join=True, room=room_name))
    )
    
    jwt_token = token.to_jwt()
    
    logger.log(
        event_name="token_issued",
        session_id=session_id,
        turn_id="system",
        detail={"room_name": room_name}
    )
    return jwt_token
