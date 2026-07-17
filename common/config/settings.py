import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

@dataclass
class Settings:
    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    
    # Deepgram
    deepgram_api_key: str
    
    # Cartesia
    cartesia_api_key: str
    
    # LLM
    groq_api_key: str
    groq_model: str
    openai_api_key: str
    openai_fallback_model: str
    
    # Redis
    redis_url: str
    
    # Qdrant (RAG)
    qdrant_url: str
    qdrant_api_key: str
    rag_enabled: bool
    
    # Enkrypt
    enkrypt_api_key: str
    enkrypt_enabled: bool
    
    # Mastra
    mastra_api_key: str
    mastra_enabled: bool
    
    # Secrets Manager
    secrets_backend: str
    
    # Observability
    otel_exporter_otlp_endpoint: str
    prometheus_pushgateway_url: str
    loki_url: str
    
    # App-wide
    log_level: str
    env: str
    session_id_header: str

_settings: Optional[Settings] = None

def load() -> Settings:
    """Reads environment variables and returns a typed Settings object.
    
    Validates variables required for the current active phase.
    """
    load_dotenv()
    
    def get_bool(key: str, default: bool = False) -> bool:
        val = os.environ.get(key)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes")

    settings = Settings(
        livekit_url=os.environ.get("LIVEKIT_URL", ""),
        livekit_api_key=os.environ.get("LIVEKIT_API_KEY", ""),
        livekit_api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
        deepgram_api_key=os.environ.get("DEEPGRAM_API_KEY", ""),
        cartesia_api_key=os.environ.get("CARTESIA_API_KEY", ""),
        groq_api_key=os.environ.get("GROQ_API_KEY", ""),
        groq_model=os.environ.get("GROQ_MODEL", "llama-3.1-70b-versatile"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_fallback_model=os.environ.get("OPENAI_FALLBACK_MODEL", "gpt-4o-mini"),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        qdrant_url=os.environ.get("QDRANT_URL", ""),
        qdrant_api_key=os.environ.get("QDRANT_API_KEY", ""),
        rag_enabled=get_bool("RAG_ENABLED", False),
        enkrypt_api_key=os.environ.get("ENKRYPT_API_KEY", ""),
        enkrypt_enabled=get_bool("ENKRYPT_ENABLED", False),
        mastra_api_key=os.environ.get("MASTRA_API_KEY", ""),
        mastra_enabled=get_bool("MASTRA_ENABLED", False),
        secrets_backend=os.environ.get("SECRETS_BACKEND", "local"),
        otel_exporter_otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        prometheus_pushgateway_url=os.environ.get("PROMETHEUS_PUSHGATEWAY_URL", ""),
        loki_url=os.environ.get("LOKI_URL", ""),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        env=os.environ.get("ENV", "development"),
        session_id_header=os.environ.get("SESSION_ID_HEADER", "x-pivot-session-id")
    )
    
    # Enforce validation incrementally based on ACTIVE_PHASE
    try:
        active_phase = int(os.environ.get("ACTIVE_PHASE", "0"))
    except ValueError:
        active_phase = 0
        
    # Phase 0 checks
    if not settings.secrets_backend:
        raise ValueError("SECRETS_BACKEND must be specified (e.g. 'local')")
        
    # Phase 1 checks
    if active_phase >= 1:
        missing = []
        if not settings.livekit_url: missing.append("LIVEKIT_URL")
        if not settings.livekit_api_key: missing.append("LIVEKIT_API_KEY")
        if not settings.livekit_api_secret: missing.append("LIVEKIT_API_SECRET")
        if not settings.deepgram_api_key: missing.append("DEEPGRAM_API_KEY")
        if not settings.cartesia_api_key: missing.append("CARTESIA_API_KEY")
        if not settings.groq_api_key: missing.append("GROQ_API_KEY")
        if missing:
            raise ValueError(f"Missing required Phase 1 variables: {', '.join(missing)}")
            
    # Phase 2 checks
    if active_phase >= 2:
        if not settings.redis_url:
            raise ValueError("REDIS_URL must be specified in Phase 2")
            
    return settings

def get_settings() -> Settings:
    """Retrieve or load global settings."""
    global _settings
    if _settings is None:
        _settings = load()
    return _settings
