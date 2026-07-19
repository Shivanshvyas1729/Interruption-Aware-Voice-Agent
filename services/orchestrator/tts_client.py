import time
import requests
from typing import Optional
from common.config.settings import get_settings
from common.config.voice_settings import get as vc_get
from common.logging.logger import get_logger

logger = get_logger("cartesia-tts")

def _mock_silence_bytes():
    silence_len = vc_get("tts.mock_chunk_silence_bytes", 16000)
    return (
        b'RIFF\x24\x3e\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00'
        b'@\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x3e\x00\x00'
        + b'\x00' * silence_len
    )

def speak(session_id: str, turn_id: str, text: str) -> bytes:
    """Synthesizes text input into audio stream bytes using Cartesia or mock fallback."""
    settings = get_settings()
    api_key = settings.cartesia_api_key
    
    start_time = time.time()
    
    # Return mock audio bytes if using dummy credentials or test mode
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        time.sleep(vc_get("tts.mock_sleep_ms", 50) / 1000.0)
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
        return _mock_silence_bytes()

    from services.orchestrator.cancellation_manager import cancellation_manager
    if cancellation_manager.is_cancelled(session_id):
        return b""

    # Real call using cartesia client
    from cartesia import Cartesia
    client = Cartesia(api_key=api_key)
    
    response = client.tts.bytes(
        model_id=vc_get("tts.model_id", "sonic-3.5"),
        transcript=text,
        voice={
            "mode": "id",
            "id": vc_get("tts.voice_id", "4459a9a5-69d6-4680-b970-e13dc51845b6")
        },
        language=vc_get("tts.language", "en"),
        output_format={
            "container": vc_get("tts.output_format.container", "wav"),
            "encoding": vc_get("tts.output_format.encoding", "pcm_s16le"),
            "sample_rate": vc_get("tts.output_format.sample_rate", 24000)
        }
    )
    
    # Consume generator/iterator if returned by Cartesia SDK
    if isinstance(response, bytes):
        audio_bytes = response
    elif hasattr(response, "__iter__") or hasattr(response, "__next__"):
        chunks = []
        for chunk in response:
            if cancellation_manager.is_cancelled(session_id):
                logger.log(
                    event_name="tts_cancelled",
                    session_id=session_id,
                    turn_id=turn_id,
                    detail={"msg": "TTS synthesis aborted mid-stream."}
                )
                return b""
            chunks.append(chunk)
        audio_bytes = b"".join(chunks)
    else:
        audio_bytes = bytes(response)
    
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
    return audio_bytes

def speak_stream(session_id: str, turn_id: str, text: str, chunk_callback) -> None:
    """Streams synthesized response audio chunks chunk-by-chunk to the callback."""
    import time
    start_time = time.time()
    settings = get_settings()
    api_key = settings.cartesia_api_key
    
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        time.sleep(vc_get("tts.mock_sleep_ms", 50) / 1000.0)
        chunk_size = vc_get("tts.chunk_size", 1600)
        words = text.split()
        num_chunks = max(10, len(words))
        mock_chunk = b'\x00' * chunk_size
        for idx in range(num_chunks):
            from services.orchestrator.cancellation_manager import cancellation_manager
            if cancellation_manager.is_cancelled(session_id):
                break
            if idx < len(words):
                on_word_timestamp(session_id, words[idx], time.time())
            chunk_callback(mock_chunk)
            time.sleep(vc_get("tts.mock_chunk_sleep_ms", 10) / 1000.0)
        return

    from services.orchestrator.cancellation_manager import cancellation_manager
    if cancellation_manager.is_cancelled(session_id):
        return

    from cartesia import Cartesia
    client = Cartesia(api_key=api_key)
    
    response = client.tts.bytes(
        model_id=vc_get("tts.model_id", "sonic-3.5"),
        transcript=text,
        voice={
            "mode": "id",
            "id": vc_get("tts.voice_id", "4459a9a5-69d6-4680-b970-e13dc51845b6")
        },
        language=vc_get("tts.language", "en"),
        output_format={
            "container": vc_get("tts.output_format.container", "wav"),
            "encoding": vc_get("tts.output_format.encoding", "pcm_s16le"),
            "sample_rate": vc_get("tts.output_format.sample_rate", 24000)
        }
    )
    
    # Stream chunks progressively
    if isinstance(response, bytes):
        chunk_callback(response)
    elif hasattr(response, "__iter__") or hasattr(response, "__next__"):
        for chunk in response:
            if cancellation_manager.is_cancelled(session_id):
                logger.log(
                    event_name="tts_cancelled",
                    session_id=session_id,
                    turn_id=turn_id,
                    detail={"msg": "TTS streaming synthesis aborted."}
                )
                break
            chunk_callback(chunk)

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
    
    settings = get_settings()
    from common.config.voice_settings import get as vc_get
    port = vc_get("ports.test_media_gateway", 8031) if settings.env == "test" else vc_get("ports.media_gateway", 8001)
    host = vc_get("urls.media_gateway_host", "127.0.0.1")
    try:
        requests.post(
            f"http://{host}:{port}/tts-control",
            json={"session_id": session_id, "action": "stop"},
            timeout=vc_get("tts.kill_timeout_s", 1)
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
    from services.orchestrator.fsm import get_fsm_for_session
    fsm = get_fsm_for_session(session_id)
    if not hasattr(fsm, "spoken_words") or fsm.spoken_words is None:
        fsm.spoken_words = []
    fsm.spoken_words.append(word)
