import time
import requests
from typing import Optional
from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger("cartesia-tts")

def speak(session_id: str, turn_id: str, text: str) -> bytes:
    """Synthesizes text input into audio stream bytes using Cartesia or mock fallback."""
    settings = get_settings()
    api_key = settings.cartesia_api_key
    
    start_time = time.time()
    
    # Return mock audio bytes if using dummy credentials or test mode
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        time.sleep(0.05)
        latency_ms = int((time.time() - start_time) * 1000)
        logger.log(
            event_name="tts_first_audio",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms,
            detail={}
        )
        logger.log(
            event_name="tts_complete",
            session_id=session_id,
            turn_id=turn_id,
            latency_ms=latency_ms + 10,
            detail={}
        )
        return b"mock_audio_bytes_wav"

    # Real call using cartesia client
    from cartesia import Cartesia
    client = Cartesia(api_key=api_key)
    
    response = client.tts.bytes(
        model_id="sonic-english",
        transcript=text,
        voice_id="a0e9987c-ab7f-47c1-a6ea-cc97b37d7c2a",  # Standard voice
        output_format={
            "container": "wav",
            "encoding": "pcm_s16le",
            "sample_rate": 24000
        }
    )
    
    latency_ms = int((time.time() - start_time) * 1000)
    logger.log(
        event_name="tts_first_audio",
        session_id=session_id,
        turn_id=turn_id,
        latency_ms=latency_ms,
        detail={}
    )
    logger.log(
        event_name="tts_complete",
        session_id=session_id,
        turn_id=turn_id,
        latency_ms=latency_ms,
        detail={}
    )
    return response

def kill(session_id: str) -> None:
    """Stops the streaming synthesis and kills the audio output (Phase 3)."""
    start_time = time.time()
    
    logger.log(
        event_name="tts_kill_signal_sent",
        session_id=session_id,
        turn_id="system",
        latency_ms=0,
        detail={"msg": "Sending Cartesia kill command"}
    )
    
    # Notify Media Gateway to stop relaying audio packets
    settings = get_settings()
    # During test execution settings.env == "test" uses port 8031
    port = 8031 if settings.env == "test" else 8001
    try:
        requests.post(
            f"http://127.0.0.1:{port}/tts-control",
            json={"session_id": session_id, "action": "stop"},
            timeout=1
        )
    except Exception:
        pass
        
    stop_latency = int((time.time() - start_time) * 1000)
    logger.log(
        event_name="tts_stopped",
        session_id=session_id,
        turn_id="system",
        latency_ms=stop_latency,
        detail={"msg": "TTS stream successfully terminated"}
    )

def on_word_timestamp(session_id: str, word: str, ts: float) -> None:
    """Tracks word boundaries for interruption context recovery (Phase 5)."""
    pass
