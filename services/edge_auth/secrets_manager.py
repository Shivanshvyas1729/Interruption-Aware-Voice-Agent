from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger("secrets-manager")

def get_secret(name: str) -> str:
    """Retrieve secret by name.
    
    Logs `secret_accessed` event without revealing the value.
    """
    settings = get_settings()
    
    # Log the access event
    logger.log(
        event_name="secret_accessed",
        session_id="system",
        turn_id="system",
        detail={"name": name}
    )
    
    # Local backend reads from the settings/environment variables
    backend = settings.secrets_backend
    if backend == "local":
        # Convert lowercase/camelCase config names to ENV style or look them up directly
        # E.g. get_secret("LIVEKIT_API_SECRET")
        attr_name = name.lower()
        if hasattr(settings, attr_name):
            return getattr(settings, attr_name)
        # Fallback to direct environment variables lookup
        import os
        return os.environ.get(name, "")
    else:
        raise NotImplementedError(f"Secrets backend {backend} is not implemented in Phase 0")
