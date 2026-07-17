"""
Application configuration loader.

This module loads environment variables, converts them into a strongly typed
Settings object, and performs phase-based validation.

Configuration is cached after the first load using `get_settings()`.
"""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Settings:
    """Application configuration."""

    # ---------------------------------------------------------------------
    # LiveKit
    # ---------------------------------------------------------------------
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # ---------------------------------------------------------------------
    # Speech Services
    # ---------------------------------------------------------------------
    deepgram_api_key: str      # Speech-to-Text
    cartesia_api_key: str      # Text-to-Speech

    # ---------------------------------------------------------------------
    # LLM Providers
    # ---------------------------------------------------------------------
    groq_api_key: str
    groq_model: str
    openai_api_key: str
    openai_fallback_model: str

    # ---------------------------------------------------------------------
    # Infrastructure
    # ---------------------------------------------------------------------
    redis_url: str

    # ---------------------------------------------------------------------
    # Retrieval (RAG)
    # ---------------------------------------------------------------------
    qdrant_url: str
    qdrant_api_key: str
    rag_enabled: bool

    # ---------------------------------------------------------------------
    # Optional Integrations
    # ---------------------------------------------------------------------
    enkrypt_api_key: str
    enkrypt_enabled: bool

    mastra_api_key: str
    mastra_enabled: bool

    # ---------------------------------------------------------------------
    # Secret Management
    # ---------------------------------------------------------------------
    secrets_backend: str

    # ---------------------------------------------------------------------
    # Observability
    # ---------------------------------------------------------------------
    otel_exporter_otlp_endpoint: str
    prometheus_pushgateway_url: str
    loki_url: str

    # ---------------------------------------------------------------------
    # Application
    # ---------------------------------------------------------------------
    log_level: str
    env: str
    session_id_header: str


# Cached singleton instance
_settings: Optional[Settings] = None


def get_env(key: str, default: str = "") -> str:
    """
    Read an environment variable.

    Returns the provided default if the variable is not defined.
    """
    return os.environ.get(key, default)


def get_bool(key: str, default: bool = False) -> bool:
    """
    Read a boolean environment variable.

    Accepted truthy values:
        true, 1, yes

    Everything else evaluates to False.
    """
    value = os.environ.get(key)

    if value is None:
        return default

    return value.lower() in {"true", "1", "yes"}


def load() -> Settings:
    """
    Load configuration from environment variables.

    Environment variables are loaded from `.env` (if present), converted into
    a typed Settings object, and validated according to the active project phase.

    Returns:
        Settings: Parsed application configuration.

    Raises:
        ValueError: If required configuration is missing.
    """
    load_dotenv()

    settings = Settings(
        # LiveKit
        livekit_url=get_env("LIVEKIT_URL"),
        livekit_api_key=get_env("LIVEKIT_API_KEY"),
        livekit_api_secret=get_env("LIVEKIT_API_SECRET"),

        # Speech
        deepgram_api_key=get_env("DEEPGRAM_API_KEY"),
        cartesia_api_key=get_env("CARTESIA_API_KEY"),

        # LLM
        groq_api_key=get_env("GROQ_API_KEY"),
        groq_model=get_env("GROQ_MODEL", "llama-3.1-70b-versatile"),
        openai_api_key=get_env("OPENAI_API_KEY"),
        openai_fallback_model=get_env(
            "OPENAI_FALLBACK_MODEL",
            "gpt-4o-mini",
        ),

        # Infrastructure
        redis_url=get_env("REDIS_URL", "redis://localhost:6379/0"),

        # RAG
        qdrant_url=get_env("QDRANT_URL"),
        qdrant_api_key=get_env("QDRANT_API_KEY"),
        rag_enabled=get_bool("RAG_ENABLED"),

        # Optional Integrations
        enkrypt_api_key=get_env("ENKRYPT_API_KEY"),
        enkrypt_enabled=get_bool("ENKRYPT_ENABLED"),

        mastra_api_key=get_env("MASTRA_API_KEY"),
        mastra_enabled=get_bool("MASTRA_ENABLED"),

        # Secrets
        secrets_backend=get_env("SECRETS_BACKEND", "local"),

        # Observability
        otel_exporter_otlp_endpoint=get_env(
            "OTEL_EXPORTER_OTLP_ENDPOINT"
        ),
        prometheus_pushgateway_url=get_env(
            "PROMETHEUS_PUSHGATEWAY_URL"
        ),
        loki_url=get_env("LOKI_URL"),

        # App
        log_level=get_env("LOG_LEVEL", "INFO"),
        env=get_env("ENV", "development"),
        session_id_header=get_env(
            "SESSION_ID_HEADER",
            "x-pivot-session-id",
        ),
    )

    # ------------------------------------------------------------------
    # Determine which project phase is currently active.
    #
    # Validation becomes progressively stricter as new functionality
    # is introduced.
    # ------------------------------------------------------------------
    try:
        active_phase = int(get_env("ACTIVE_PHASE", "0"))
    except ValueError:
        active_phase = 0

    # ------------------------------------------------------------------
    # Phase 0
    #
    # Basic application configuration.
    # ------------------------------------------------------------------
    if not settings.secrets_backend:
        raise ValueError(
            "SECRETS_BACKEND must be specified "
            "(e.g. 'local')."
        )

    # ------------------------------------------------------------------
    # Phase 1
    #
    # Voice agent dependencies.
    # ------------------------------------------------------------------
    if active_phase >= 1:
        missing = []

        required = {
            "LIVEKIT_URL": settings.livekit_url,
            "LIVEKIT_API_KEY": settings.livekit_api_key,
            "LIVEKIT_API_SECRET": settings.livekit_api_secret,
            "DEEPGRAM_API_KEY": settings.deepgram_api_key,
            "CARTESIA_API_KEY": settings.cartesia_api_key,
            "GROQ_API_KEY": settings.groq_api_key,
        }

        missing.extend(
            name for name, value in required.items() if not value
        )

        if missing:
            raise ValueError(
                "Missing required Phase 1 variables: "
                + ", ".join(missing)
            )

    # ------------------------------------------------------------------
    # Phase 2
    #
    # Stateful infrastructure.
    # ------------------------------------------------------------------
    if active_phase >= 2:
        if not settings.redis_url:
            raise ValueError(
                "REDIS_URL must be specified in Phase 2."
            )

    return settings


def get_settings() -> Settings:
    """
    Return the singleton Settings instance.

    The configuration is loaded only once during the application lifetime.
    Subsequent calls return the cached instance.
    """
    global _settings

    if _settings is None:
        _settings = load()

    return _settings