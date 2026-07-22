import time
import requests
from typing import Optional
from common.config.settings import get_settings
from common.config.voice_settings import get as vc_get
from common.logging.logger import get_logger

import threading
from requests.adapters import HTTPAdapter

logger = get_logger("cartesia-tts")

_cartesia_clients = {}
_client_lock = threading.Lock()
_requests_session = None
_session_lock = threading.Lock()

def get_cartesia_client(api_key: str):
    with _client_lock:
        if api_key not in _cartesia_clients:
            from cartesia import Cartesia
            _cartesia_clients[api_key] = Cartesia(api_key=api_key)
        return _cartesia_clients[api_key]

def get_requests_session() -> requests.Session:
    global _requests_session
    with _session_lock:
        if _requests_session is None:
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=200, pool_maxsize=200)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            _requests_session = s
        return _requests_session


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
    client = get_cartesia_client(api_key)
    
    response = client.tts.bytes(
        model_id=vc_get("tts.model_id", "sonic-3.5"),
        transcript=text,
        voice={
            "mode": "id",
            "id": vc_get("tts.voice_id", "4459a9a5-69d6-4680-b970-e13dc51845b6")
        },
        language=vc_get("tts.language", "en"),
        output_format={
            "container": vc_get("tts.output_format.container", "raw"),
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
    from services.orchestrator.cancellation_manager import cancellation_manager
    from services.orchestrator.async_pipeline import get_current_turn
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
            if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
                break
            if idx < len(words):
                on_word_timestamp(session_id, words[idx], time.time())
            chunk_callback(mock_chunk)
            time.sleep(vc_get("tts.mock_chunk_sleep_ms", 10) / 1000.0)
        return

    if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
        return

    client = get_cartesia_client(api_key)
    
    response = client.tts.bytes(
        model_id=vc_get("tts.model_id", "sonic-3.5"),
        transcript=text,
        voice={
            "mode": "id",
            "id": vc_get("tts.voice_id", "4459a9a5-69d6-4680-b970-e13dc51845b6")
        },
        language=vc_get("tts.language", "en"),
        output_format={
            "container": vc_get("tts.output_format.container", "raw"),
            "encoding": vc_get("tts.output_format.encoding", "pcm_s16le"),
            "sample_rate": vc_get("tts.output_format.sample_rate", 24000)
        }
    )
    
    # Stream chunks progressively
    if isinstance(response, bytes):
        chunk_callback(response)
    elif hasattr(response, "__iter__") or hasattr(response, "__next__"):
        for chunk in response:
            from services.orchestrator.async_pipeline import get_current_turn
            if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
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
        get_requests_session().post(
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

def speak_stream_ws(session_id: str, turn_id: str, text: str, chunk_callback) -> None:
    """Streams synthesized response audio using Cartesia WebSocket connection with real timestamps."""
    import time
    start_time = time.time()
    settings = get_settings()
    api_key = settings.cartesia_api_key

    # Return mock audio bytes if using dummy credentials or test mode
    if not api_key or api_key == "dummy_val" or settings.env == "test":
        # Fall back to speak_stream mock branch
        speak_stream(session_id, turn_id, text, chunk_callback)
        return

    from services.orchestrator.cancellation_manager import cancellation_manager
    from services.orchestrator.async_pipeline import get_current_turn
    if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
        return

    try:
        client = get_cartesia_client(api_key)
        ws = client.tts.websocket_connect().enter()
    except Exception as e:
        logger.log_error("tts_ws_connect_failed", session_id, turn_id, e)
        logger.log(
            event_name="tts_ws_fallback",
            session_id=session_id,
            turn_id=turn_id,
            detail={"msg": "Falling back to REST speak_stream due to connection failure."}
        )
        speak_stream(session_id, turn_id, text, chunk_callback)
        return

    context_id = f"{session_id}:{turn_id}"
    try:
        ctx = ws.context(
            context_id=context_id,
            model_id=vc_get("tts.model_id", "sonic-3.5"),
            voice={
                "mode": "id",
                "id": vc_get("tts.voice_id", "4459a9a5-69d6-4680-b970-e13dc51845b6")
            },
            output_format={
                "container": "raw",
                "encoding": vc_get("tts.output_format.encoding", "pcm_s16le"),
                "sample_rate": vc_get("tts.output_format.sample_rate", 24000)
            },
            add_timestamps=True
        )

        ctx.push(text, continue_=False)

        first_audio_logged = False
        for event in ctx.receive():
            from services.orchestrator.async_pipeline import get_current_turn
            if cancellation_manager.is_cancelled(session_id) or int(turn_id) < get_current_turn(session_id):
                logger.log(
                    event_name="tts_ws_cancelled",
                    session_id=session_id,
                    turn_id=turn_id,
                    detail={"msg": "Cancellation detected, sending cancel event to Cartesia"}
                )
                try:
                    ctx.cancel()
                except Exception as ce:
                    logger.log_error("tts_ws_cancel_failed", session_id, turn_id, ce)
                break

            if event.type == "chunk":
                if event.audio:
                    if not first_audio_logged:
                        first_audio_logged = True
                        latency_ms = int((time.time() - start_time) * 1000)
                        logger.log(
                            event_name="tts_first_audio",
                            session_id=session_id,
                            turn_id=turn_id,
                            latency_ms=latency_ms,
                            detail={"transport": "websocket"}
                        )
                    chunk_callback(event.audio)
            elif event.type == "timestamps":
                if hasattr(event, "word_timestamps") and event.word_timestamps:
                    words = getattr(event.word_timestamps, "words", []) or []
                    starts = getattr(event.word_timestamps, "start", []) or []
                    for w, t in zip(words, starts):
                        on_word_timestamp(session_id, w, t)
            elif event.type == "error":
                raise RuntimeError(f"Cartesia WS error event: {event.error}")
            elif event.type == "done":
                break
    except Exception as e:
        logger.log_error("tts_ws_stream_failed", session_id, turn_id, e)
        raise
    finally:
        try:
            ws.close()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Sentence-level WebSocket helpers (Problem #4b)
# ---------------------------------------------------------------------------

# Process-scoped capability cache for ctx.push(..., continue_=True).
# None  = not yet probed
# True  = supported (Cartesia context continuation is available)
# False = not supported (fall back to per-sentence speak_stream_ws)
_ws_continuation_supported: Optional[bool] = None


def open_ws_context(session_id: str, turn_id: Optional[str] = None):
    """
    Open a Cartesia WebSocket and create a session-scoped context.

    Returns (ws, ctx) — the caller is responsible for calling close_ws_context()
    when the session ends or when an exception occurs.
    """
    settings = get_settings()
    api_key = settings.cartesia_api_key

    client = get_cartesia_client(api_key)
    ws = client.tts.websocket_connect().enter()
    context_id = f"session_{session_id}"
    ctx = ws.context(
        context_id=context_id,
        model_id=vc_get("tts.model_id", "sonic-3.5"),
        voice={
            "mode": "id",
            "id": vc_get("tts.voice_id", "4459a9a5-69d6-4680-b970-e13dc51845b6"),
        },
        output_format={
            "container": "raw",
            "encoding": vc_get("tts.output_format.encoding", "pcm_s16le"),
            "sample_rate": vc_get("tts.output_format.sample_rate", 24000),
        },
        add_timestamps=True,
    )
    return ws, ctx


def speak_sentence_ws(
    session_id: str,
    turn_id: str,
    text: str,
    chunk_callback,
    ws_ctx,
    continue_: bool,
) -> None:
    """
    Push one sentence into an already-open Cartesia context and stream the
    resulting audio chunks via chunk_callback.

    continue_=True for sentences 1..N-1; continue_=False for the final sentence.

    If the SDK does not support ctx.push(..., continue_=True) a TypeError is
    raised — the caller (TTSWorker._tts_sync) catches it, sets
    _ws_continuation_supported=False, and re-calls speak_stream_ws directly.
    """
    from services.orchestrator.cancellation_manager import cancellation_manager
    if cancellation_manager.is_cancelled(session_id):
        return

    start_time = time.time()

    try:
        ws_ctx.push(text, continue_=continue_)
    except (TypeError, AttributeError) as probe_err:
        logger.log(
            event_name="tts_ws_continuation_unsupported",
            session_id=session_id,
            turn_id=turn_id,
            detail={"error": str(probe_err), "fallback": "speak_stream_ws"},
        )
        raise  # TTSWorker catches this to degrade gracefully

    first_audio_logged = False

    for event in ws_ctx.receive():
        if cancellation_manager.is_cancelled(session_id):
            logger.log(
                event_name="tts_ws_cancelled",
                session_id=session_id,
                turn_id=turn_id,
                detail={"msg": "Cancellation detected mid-sentence"},
            )
            try:
                ws_ctx.cancel()
            except Exception as ce:
                logger.log_error("tts_ws_cancel_failed", session_id, turn_id, ce)
            break

        if event.type == "chunk":
            if event.audio:
                if not first_audio_logged:
                    first_audio_logged = True
                    latency_ms = int((time.time() - start_time) * 1000)
                    logger.log(
                        event_name="tts_first_audio",
                        session_id=session_id,
                        turn_id=turn_id,
                        latency_ms=latency_ms,
                        detail={"transport": "websocket_sentence"},
                    )
                chunk_callback(event.audio)
        elif event.type == "timestamps":
            if hasattr(event, "word_timestamps") and event.word_timestamps:
                words = getattr(event.word_timestamps, "words", []) or []
                starts = getattr(event.word_timestamps, "start", []) or []
                for w, t in zip(words, starts):
                    on_word_timestamp(session_id, w, t)
        elif event.type == "error":
            raise RuntimeError(f"Cartesia WS error event: {event.error}")
        elif event.type == "done":
            break


def close_ws_context(ws, session_id: str, turn_id: str) -> None:
    """
    Best-effort close of a Cartesia WebSocket.  Never raises — safe to call
    from finally blocks and cleanup paths.
    """
    try:
        ws.close()
    except Exception as e:
        logger.log_error("tts_ws_close_failed", session_id, turn_id, e)


def on_word_timestamp(session_id: str, word: str, ts: float) -> None:
    """Tracks word boundaries for interruption context recovery (Phase 5)."""
    # Option B: Preserve dual-write for legacy /chat endpoint using fsm.py
    try:
        from services.orchestrator.fsm import get_fsm_for_session
        fsm = get_fsm_for_session(session_id)
        if fsm is not None:
            if not hasattr(fsm, "spoken_words") or fsm.spoken_words is None:
                fsm.spoken_words = []
            fsm.spoken_words.append(word)
    except Exception:
        pass

    # Report to the active live pipeline FSM worker thread-safely
    try:
        from services.orchestrator.async_pipeline import get_pipeline, WordMessage, _main_loop
        pipeline = get_pipeline()
        if pipeline and pipeline.fsm and hasattr(pipeline.fsm, "word_input") and pipeline.fsm.word_input and _main_loop:
            _main_loop.call_soon_threadsafe(
                pipeline.fsm.word_input.put_nowait,
                WordMessage(session_id=session_id, word=word)
            )
    except Exception:
        pass
