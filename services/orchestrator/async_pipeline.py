"""
Fully async pipeline with dedicated workers for every stage.

Architecture:
  STT Worker → FSM Worker → LLM Worker → TTS Worker → Playback Worker
                  ↑               ↑
           Interrupt Monitor  Cancellation Manager
                  ↓               ↓
             Metrics Worker (telemetry bus)

Every blocking SDK call is offloaded via loop.run_in_executor.
"""

import asyncio
import time
import json
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
from common.config.settings import get_settings
from common.config.voice_settings import get as vc_get
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from services.orchestrator.context_manager import (
    prepare_context, get_token_budget, reset_token_budget, TokenBudget,
)

logger = get_logger("async-pipeline")

# ---------------------------------------------------------------------------
# Messages passed between workers
# ---------------------------------------------------------------------------

@dataclass
class TranscriptMessage:
    text: str
    session_id: str
    turn_id: int
    is_final: bool = True
    stt_latency_ms: int = 0

@dataclass
class LLMRequest:
    messages: list[dict]
    session_id: str
    turn_id: int
    max_tokens: int | None = None
    max_sentences: int | None = None

@dataclass
class LLMResponse:
    text: str
    session_id: str
    turn_id: int
    tokens: int = 0
    latency_ms: int = 0

@dataclass
class TextResponse:
    text: str
    session_id: str
    turn_id: int
    tokens: int = 0
    latency_ms: int = 0

@dataclass
class LLMSentenceChunk:
    """One sentence emitted by LLMWorker; is_final marks the last sentence of a turn."""
    text: str
    session_id: str
    turn_id: int
    sentence_index: int
    is_final: bool = False
    # Populated only on is_final=True — carries full accumulated reply for metrics/pending-store.
    full_reply_text: str = ""
    tokens: int = 0
    latency_ms: int = 0

@dataclass
class TTSRequest:
    text: str
    session_id: str
    turn_id: int
    is_final_sentence: bool = False  # gates AudioChunk(is_last=True) in TTSWorker

@dataclass
class AudioChunk:
    data: bytes
    session_id: str
    turn_id: int
    is_last: bool = False

@dataclass
class InterruptEvent:
    session_id: str
    kind: str  # "vad_start", "stop_button", "barge_in"
    detail: dict = field(default_factory=dict)

@dataclass
class CancelCommand:
    session_id: str
    reason: str

@dataclass
class MetricsEvent:
    event_type: str
    session_id: str
    turn_id: str
    data: dict = field(default_factory=dict)

@dataclass
class FSMTransition:
    session_id: str
    turn_id: int
    new_state: str
    data: dict = field(default_factory=dict)

@dataclass
class WordMessage:
    session_id: str
    word: str

@dataclass
class PlaybackDoneMessage:
    session_id: str
    turn_id: int

# ---------------------------------------------------------------------------
# Cancellation token — lightweight per-session flag
# ---------------------------------------------------------------------------

class CancelToken:
    __slots__ = ("_cancelled", "_reason", "_event")
    def __init__(self):
        self._cancelled = False
        self._reason = ""
        self._event = asyncio.Event()

    def cancel(self, reason: str = ""):
        self._cancelled = True
        self._reason = reason
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    async def wait(self):
        await self._event.wait()

    def reset(self):
        self._cancelled = False
        self._reason = ""
        self._event.clear()


_tokens: dict[str, CancelToken] = {}

def get_cancel_token(session_id: str) -> CancelToken:
    if session_id not in _tokens:
        _tokens[session_id] = CancelToken()
    return _tokens[session_id]

def reset_cancel_token(session_id: str):
    tok = _tokens.get(session_id)
    if tok:
        tok.reset()

def cleanup_session(session_id: str) -> None:
    """Remove all module-level per-session state.
    Called when a WebSocket client disconnects so long-running servers
    don't accumulate unbounded dictionaries.
    """
    _tokens.pop(session_id, None)
    _current_turn.pop(session_id, None)
    from services.orchestrator.cancellation_manager import cancellation_manager
    cancellation_manager.cleanup_session(session_id)


# ---------------------------------------------------------------------------
# Turn-scoped cancellation — current active turn per session
# ---------------------------------------------------------------------------

_current_turn: dict[str, int] = {}

def get_current_turn(session_id: str) -> int:
    """Return the session's currently-active turn_id (0 if not yet set)."""
    return _current_turn.get(session_id, 0)

def set_current_turn(session_id: str, turn_id: int) -> None:
    """Advance the session's active turn_id. Called by FSMWorker on each new transcript."""
    _current_turn[session_id] = turn_id


class PipelineError(Exception):
    pass

# ---------------------------------------------------------------------------
# Base worker
# ---------------------------------------------------------------------------

class PipelineStage(ABC):
    def __init__(self, name: str):
        self.name = name
        self._task: asyncio.Task | None = None
        self._cancel_event = asyncio.Event()

    @abstractmethod
    async def run(self):
        ...

    def start(self):
        if self._task is None or self._task.done():
            self._cancel_event.clear()
            self._task = asyncio.create_task(self._run_wrapper(), name=self.name)
            logger.log_service_start(self.name)

    async def stop(self):
        self._cancel_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.log_service_stop(self.name)

    async def _run_wrapper(self):
        try:
            await self.run()
        except asyncio.CancelledError:
            logger.log("pipeline_stage_cancelled", "system", "system",
                       detail={"stage": self.name})
        except Exception as e:
            logger.log_error("pipeline_stage_error", "system", "system", e, stage=self.name)
            traceback.print_exc()

# ---------------------------------------------------------------------------
# STT Worker
# ---------------------------------------------------------------------------

class STTWorker(PipelineStage):
    def __init__(self):
        super().__init__("stt")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()

    async def run(self):
        while not self._cancel_event.is_set():
            try:
                msg = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            try:
                # Browser sends text (Web Speech API), pass through directly.
                # For future raw-audio mode, this worker would call Deepgram.
                telemetry_bus.push("stt_final", {"text": msg.text[:80]},
                                   msg.session_id, str(msg.turn_id))
                await self.output.put(TranscriptMessage(
                    text=msg.text, session_id=msg.session_id,
                    turn_id=msg.turn_id, is_final=True))
            except Exception as e:
                logger.log_error("stt_worker_error", msg.session_id if 'msg' in locals() else "system", "system", e)
                telemetry_bus.push("error", {"message": f"STT Stage Error: {str(e)}"}, msg.session_id if 'msg' in locals() else "system", "system")

# ---------------------------------------------------------------------------
# LLM Worker
# ---------------------------------------------------------------------------

class LLMWorker(PipelineStage):
    def __init__(self):
        super().__init__("llm")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()
        # Per-session last task — chaining preserves intra-session ordering
        # while allowing unrelated sessions to run concurrently.
        self._session_tasks: dict[str, asyncio.Task] = {}
        self.executor = None

    def start(self):
        from concurrent.futures import ThreadPoolExecutor
        from common.config import voice_settings
        max_workers = voice_settings.get("concurrency.llm_max_workers", 100)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm_worker")
        super().start()

    async def stop(self):
        await super().stop()
        if self.executor:
            self.executor.shutdown(wait=False)


    async def run(self):
        while not self._cancel_event.is_set():
            try:
                req = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            tok = get_cancel_token(req.session_id)
            if tok.is_cancelled:
                continue

            # Chain this request behind the prior task for the same session so
            # that within-session ordering is preserved while other sessions
            # execute concurrently.
            prev_task = self._session_tasks.get(req.session_id)
            task = asyncio.create_task(
                self._process_request(req, prev_task),
                name=f"llm-{req.session_id}-{req.turn_id}",
            )
            self._session_tasks[req.session_id] = task

            # Remove the session entry once the task completes so the dict
            # doesn't grow unboundedly.
            def _on_done(t, sid=req.session_id):
                if self._session_tasks.get(sid) is t:
                    self._session_tasks.pop(sid, None)
            task.add_done_callback(_on_done)

    async def _process_request(self, req: "LLMRequest", prev_task: "asyncio.Task | None"):
        """Process one LLM request.  Waits for the prior task from the same
        session before starting so turn ordering is guaranteed within a session."""
        if prev_task is not None:
            if not prev_task.done():
                try:
                    await prev_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.log_error("llm_prior_task_failed", req.session_id, str(req.turn_id), e)
            else:
                # Retrieve exception if already done to log it and prevent
                # "Task exception was never retrieved" warnings.
                if not prev_task.cancelled():
                    try:
                        exc = prev_task.exception()
                        if exc is not None:
                            logger.log_error("llm_prior_task_failed", req.session_id, str(req.turn_id), exc)
                    except Exception:
                        pass

        tok = get_cancel_token(req.session_id)
        if tok.is_cancelled:
            return

        logger.log("llm_request_received", req.session_id, str(req.turn_id),
                   detail={"messages": len(req.messages)})

        loop = asyncio.get_event_loop()
        t0 = time.time()
        try:
            from services.orchestrator.llm_client import call_primary_streaming
            from services.orchestrator.failover import primary_circuit_breaker
            from services.orchestrator.context_manager import estimate_tokens

            # Lookahead-1 buffer: dispatch sentence[N-1] as is_final=False when
            # sentence[N] arrives; dispatch sentence[last] as is_final=True after
            # call_primary_streaming returns.  All dispatches happen on the executor
            # thread via run_coroutine_threadsafe so ordering is guaranteed.
            pending: list = [None]   # [(sentence_index, text)] or [None]
            sentence_index: list = [0]
            output_q = self.output

            max_sentences = req.max_sentences if req.max_sentences is not None else vc_get("llm.max_sentences", 3)

            def _sentence_callback(sentence_text: str) -> None:
                idx = sentence_index[0]
                # Enforce max_sentences: stop dispatching once the limit is hit.
                if idx >= max_sentences:
                    return
                sentence_index[0] += 1
                if pending[0] is not None:
                    prev_idx, prev_text = pending[0]
                    if not tok.is_cancelled:
                        asyncio.run_coroutine_threadsafe(
                            output_q.put(LLMSentenceChunk(
                                text=prev_text,
                                session_id=req.session_id,
                                turn_id=req.turn_id,
                                sentence_index=prev_idx,
                                is_final=False,
                            )),
                            loop,
                        )
                pending[0] = (idx, sentence_text)

            def _llm_streaming_task() -> str:
                """Runs in executor thread.  Streams sentences; dispatches all
                but the last immediately; dispatches the last with is_final=True
                before returning so FSM always sees a terminal chunk."""
                try:
                    # Dynamically inject system instructions matching the requested length
                    system_prompt = None
                    if req.max_sentences and req.max_sentences > 3:
                        system_prompt = (
                            "You are a helpful voice assistant. Provide a detailed, descriptive response "
                            "addressing the query in depth. Keep sentences clear but informative."
                        )
                    full_text = call_primary_streaming(
                        req.session_id, str(req.turn_id), req.messages,
                        _sentence_callback,
                        max_tokens=req.max_tokens,
                        system_prompt=system_prompt,
                    )
                except Exception:
                    # Dispatch an error sentence as the terminal chunk so the
                    # pending-response store and PlaybackDone signal always fire.
                    if not tok.is_cancelled:
                        asyncio.run_coroutine_threadsafe(
                            output_q.put(LLMSentenceChunk(
                                text="I'm sorry, I encountered an error.",
                                session_id=req.session_id,
                                turn_id=req.turn_id,
                                sentence_index=sentence_index[0],
                                is_final=True,
                                full_reply_text="I'm sorry, I encountered an error.",
                                tokens=0,
                                latency_ms=int((time.time() - t0) * 1000),
                            )),
                            loop,
                        ).result()  # block until queued — must arrive after preceding chunks
                    raise

                # Guarantee exactly one is_final=True terminal chunk per turn.
                # When pending[0] is None (no sentence boundary was found — e.g.
                # single-word reply, no punctuation, empty string, or stream
                # cancelled before any boundary), use full_text directly as the
                # sole chunk.  This prevents silent turn death.
                if not tok.is_cancelled:
                    tokens = estimate_tokens(full_text)
                    if pending[0] is not None:
                        final_idx, final_text = pending[0]
                    else:
                        # No sentence callback ever fired — treat the entire
                        # accumulated text as a single terminal sentence.
                        final_idx, final_text = 0, full_text
                    asyncio.run_coroutine_threadsafe(
                        output_q.put(LLMSentenceChunk(
                            text=final_text,
                            session_id=req.session_id,
                            turn_id=req.turn_id,
                            sentence_index=final_idx,
                            is_final=True,
                            full_reply_text=full_text,
                            tokens=tokens,
                            latency_ms=int((time.time() - t0) * 1000),
                        )),
                        loop,
                    ).result()  # block until queued

                return full_text

            reply_text = await loop.run_in_executor(self.executor, _llm_streaming_task)

            if tok.is_cancelled:
                logger.log("llm_cancelled_post_executor", req.session_id, str(req.turn_id), detail={})
                return

            provider = "openai" if primary_circuit_breaker.is_open() else "groq"
            logger.log("llm_turn_dispatched", req.session_id, str(req.turn_id),
                       detail={"provider": provider, "sentences": sentence_index[0]})

        except Exception as outer_err:
            logger.log_error("llm_worker_processing_failed", req.session_id, str(req.turn_id), outer_err)
            telemetry_bus.push("error", {"message": f"LLM Stage Error: {str(outer_err)}"},
                               req.session_id, str(req.turn_id))
            # The error terminal chunk was already dispatched inside _llm_streaming_task




# ---------------------------------------------------------------------------
# TTS Worker
# ---------------------------------------------------------------------------

class TTSWorker(PipelineStage):
    def __init__(self):
        super().__init__("tts")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()
        # Per-turn open WS contexts: turn_key -> (ws, ctx)
        # Written/read only from _tts_sync (one executor thread at a time per session).
        self._ws_sessions: dict[str, Any] = {}
        # Per-session last task — chaining preserves intra-session ordering
        # while allowing unrelated sessions to synthesise concurrently.
        self._session_tasks: dict[str, asyncio.Task] = {}
        self.executor = None

    def start(self):
        from concurrent.futures import ThreadPoolExecutor
        from common.config import voice_settings
        max_workers = voice_settings.get("concurrency.tts_max_workers", 200)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tts_worker")
        super().start()

    async def stop(self):
        """Override to close any open WS contexts and shut down executor before the task is cancelled."""
        await super().stop()
        if self.executor:
            self.executor.shutdown(wait=False)
        # Best-effort cleanup of contexts that were open when shutdown arrived.
        from services.orchestrator.tts_client import close_ws_context
        for turn_key, (ws, _) in list(self._ws_sessions.items()):
            # turn_key is "session_id:turn_id" — extract session_id for logging
            session_id = turn_key.rsplit(":", 1)[0]
            close_ws_context(ws, session_id, "shutdown")
        self._ws_sessions.clear()



    async def run(self):
        while not self._cancel_event.is_set():
            try:
                req = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            # Early cancellation / stale-turn check before spawning a task
            tok = get_cancel_token(req.session_id)
            if tok.is_cancelled:
                logger.log("tts_skipped_cancelled", req.session_id, str(req.turn_id), detail={})
                continue

            current_turn = get_current_turn(req.session_id)
            if req.turn_id < current_turn:
                logger.log("tts_skipped_stale_turn", req.session_id, str(req.turn_id),
                           detail={"current_turn": current_turn})
                continue

            # Chain behind the prior task for this session so sentence order
            # is preserved while concurrent sessions execute in parallel.
            prev_task = self._session_tasks.get(req.session_id)
            task = asyncio.create_task(
                self._process_request(req, prev_task),
                name=f"tts-{req.session_id}-{req.turn_id}",
            )
            self._session_tasks[req.session_id] = task

            def _on_done(t, sid=req.session_id):
                if self._session_tasks.get(sid) is t:
                    self._session_tasks.pop(sid, None)
            task.add_done_callback(_on_done)

    async def _process_request(self, req: "TTSRequest", prev_task: "asyncio.Task | None"):
        """Process one TTS sentence request.  Waits for the prior task from the
        same session to preserve sentence ordering within a turn."""
        if prev_task is not None:
            if not prev_task.done():
                try:
                    await prev_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.log_error("tts_prior_task_failed", req.session_id, str(req.turn_id), e)
            else:
                # Retrieve exception if already done to log it and prevent
                # "Task exception was never retrieved" warnings.
                if not prev_task.cancelled():
                    try:
                        exc = prev_task.exception()
                        if exc is not None:
                            logger.log_error("tts_prior_task_failed", req.session_id, str(req.turn_id), exc)
                    except Exception:
                        pass

        # Re-check guards after awaiting the previous task (state may have changed)
        tok = get_cancel_token(req.session_id)
        if tok.is_cancelled:
            logger.log("tts_skipped_cancelled_post_wait", req.session_id, str(req.turn_id), detail={})
            turn_key = f"{req.session_id}:{req.turn_id}"
            if turn_key in self._ws_sessions:
                from services.orchestrator.tts_client import close_ws_context
                ws, _ = self._ws_sessions.pop(turn_key)
                close_ws_context(ws, req.session_id, str(req.turn_id))
            return

        current_turn = get_current_turn(req.session_id)
        if req.turn_id < current_turn:
            logger.log("tts_skipped_stale_turn", req.session_id, str(req.turn_id),
                       detail={"current_turn": current_turn})
            turn_key = f"{req.session_id}:{req.turn_id}"
            if turn_key in self._ws_sessions:
                from services.orchestrator.tts_client import close_ws_context
                ws, _ = self._ws_sessions.pop(turn_key)
                close_ws_context(ws, req.session_id, str(req.turn_id))
            return

        try:
            logger.log("tts_request_received", req.session_id, str(req.turn_id),
                       detail={"text": req.text[:60],
                               "is_final_sentence": req.is_final_sentence})

            settings = get_settings()
            api_key = settings.cartesia_api_key
            mock = not api_key or api_key == "dummy_val" or settings.env == "test"
            logger.log("tts_starting", req.session_id, str(req.turn_id),
                       detail={"mock": mock})

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor, self._tts_sync, api_key, req, mock, loop)
        except Exception as e:
            logger.log_error("tts_worker_processing_failed", req.session_id, str(req.turn_id), e)
            telemetry_bus.push("error", {"message": f"TTS Stage Error: {str(e)}"},
                               req.session_id, str(req.turn_id))
            # Push terminal cap to prevent client hanging
            await self.output.put(AudioChunk(b"", req.session_id, req.turn_id, True))



    def _tts_sync(self, api_key: str, req: TTSRequest, mock: bool,
                  loop: asyncio.AbstractEventLoop) -> None:
        """Runs in executor thread.  Manages per-turn WS context lifecycle."""
        from services.orchestrator.tts_client import (
            _ws_continuation_supported,
            open_ws_context, speak_sentence_ws, close_ws_context,
            speak_stream_ws,
        )
        start_time = time.time()
        turn_key = f"{req.session_id}:{req.turn_id}"
        loop.call_soon_threadsafe(
            telemetry_bus.push, "tts_start",
            {"sentence_idx": 0, "is_final": req.is_final_sentence},
            req.session_id, str(req.turn_id),
        )

        def chunk_callback(chunk_data: bytes) -> None:
            if get_cancel_token(req.session_id).is_cancelled:
                return
            # Turn-scoped guard inside the synthesis callback: discard bytes
            # synthesised for a turn that has already been superseded.
            if get_current_turn(req.session_id) != req.turn_id:
                return
            loop.call_soon_threadsafe(
                telemetry_bus.push, "tts_chunk",
                {"sentence": req.text[:40]}, req.session_id, str(req.turn_id),
            )
            asyncio.run_coroutine_threadsafe(
                self.output.put(AudioChunk(chunk_data, req.session_id, req.turn_id, False)),
                loop,
            )

        # ------------------------------------------------------------------
        # Mock path or capability known-unsupported: one speak_stream_ws per sentence
        # ------------------------------------------------------------------
        use_fallback = mock or (_ws_continuation_supported is False)
        if use_fallback:
            try:
                speak_stream_ws(req.session_id, str(req.turn_id), req.text, chunk_callback)
                tok = get_cancel_token(req.session_id)
                if req.is_final_sentence and not tok.is_cancelled:
                    asyncio.run_coroutine_threadsafe(
                        self.output.put(AudioChunk(b"", req.session_id, req.turn_id, True)),
                        loop,
                    )
                    latency_ms = int((time.time() - start_time) * 1000)
                    loop.call_soon_threadsafe(
                        telemetry_bus.push, "tts_complete",
                        {"latency_ms": latency_ms}, req.session_id, str(req.turn_id),
                    )
            except Exception as e:
                logger.log_error("tts_sync_error", req.session_id, str(req.turn_id), e)
                # Always cap the turn on any failure so PlaybackDone fires
                get_cancel_token(req.session_id).cancel("tts_synthesis_error")
                asyncio.run_coroutine_threadsafe(
                    self.output.put(AudioChunk(b"", req.session_id, req.turn_id, True)),
                    loop,
                )
            return

        # ------------------------------------------------------------------
        # Real Cartesia path: shared WS context per turn
        # ------------------------------------------------------------------
        failed = False
        try:
            # Open context on first sentence of this turn
            if turn_key not in self._ws_sessions:
                try:
                    ws, ctx = open_ws_context(req.session_id, str(req.turn_id))
                    self._ws_sessions[turn_key] = (ws, ctx)
                except Exception as conn_err:
                    logger.log_error("tts_ws_open_failed", req.session_id, str(req.turn_id), conn_err)
                    # Degrade: this sentence and subsequent ones use speak_stream_ws
                    speak_stream_ws(req.session_id, str(req.turn_id), req.text, chunk_callback)
                    tok = get_cancel_token(req.session_id)
                    if req.is_final_sentence and not tok.is_cancelled:
                        asyncio.run_coroutine_threadsafe(
                            self.output.put(AudioChunk(b"", req.session_id, req.turn_id, True)),
                            loop,
                        )
                    return

            _, ctx = self._ws_sessions[turn_key]

            try:
                speak_sentence_ws(
                    req.session_id, str(req.turn_id), req.text, chunk_callback,
                    ctx, continue_=not req.is_final_sentence,
                )
            except (TypeError, AttributeError):
                # capability probe failed — fallback is already set in speak_sentence_ws;
                # close this context and re-run this sentence via speak_stream_ws
                import services.orchestrator.tts_client as _tc
                _tc._ws_continuation_supported = False
                failed = True  # triggers finally cleanup
                raise

            tok = get_cancel_token(req.session_id)
            if req.is_final_sentence and not tok.is_cancelled:
                asyncio.run_coroutine_threadsafe(
                    self.output.put(AudioChunk(b"", req.session_id, req.turn_id, True)),
                    loop,
                )
                latency_ms = int((time.time() - start_time) * 1000)
                loop.call_soon_threadsafe(
                    telemetry_bus.push, "tts_complete",
                    {"latency_ms": latency_ms}, req.session_id, str(req.turn_id),
                )

        except Exception as e:
            failed = True
            logger.log_error("tts_sync_error", req.session_id, str(req.turn_id), e)
            # Cap the turn and drain subsequent queued sentences for this turn
            get_cancel_token(req.session_id).cancel("tts_synthesis_error")
            asyncio.run_coroutine_threadsafe(
                self.output.put(AudioChunk(b"", req.session_id, req.turn_id, True)),
                loop,
            )

        finally:
            # Close WS context on final sentence, cancellation, or any exception
            tok = get_cancel_token(req.session_id)
            should_close = req.is_final_sentence or tok.is_cancelled or failed
            if should_close and turn_key in self._ws_sessions:
                ws, _ = self._ws_sessions.pop(turn_key)
                close_ws_context(ws, req.session_id, str(req.turn_id))


# ---------------------------------------------------------------------------
# Playback Worker — sends audio to WebSocket clients
# ---------------------------------------------------------------------------

class PlaybackWorker(PipelineStage):
    def __init__(self):
        super().__init__("playback")
        self.input: asyncio.Queue = asyncio.Queue()
        self._clients: dict[str, asyncio.Queue] = {}
        self._playback_started: dict[str, float] = {}  # session_id -> start_time
        self._spoken_duration: dict[str, float] = {}  # session_id -> float
        
        # Per-session internal queues and delivery tasks to isolate slow-client blocking
        self._session_queues: dict[str, asyncio.Queue] = {}
        self._session_tasks: dict[str, asyncio.Task] = {}
        self._dying_tasks: set[asyncio.Task] = set()

    def register_client(self, session_id: str, queue: asyncio.Queue):
        self._clients[session_id] = queue
        self._spoken_duration[session_id] = 0.0
        
        # Instantiate session-specific internal queue and delivery task
        self._session_queues[session_id] = asyncio.Queue()
        self._session_tasks[session_id] = asyncio.create_task(
            self._process_session(session_id),
            name=f"playback-session-{session_id}"
        )

    def unregister_client(self, session_id: str):
        self._clients.pop(session_id, None)
        self._spoken_duration.pop(session_id, None)
        self._playback_started.pop(session_id, None)
        
        # Clean up session queue and cancel the delivery task
        self._session_queues.pop(session_id, None)
        task = self._session_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            self._dying_tasks.add(task)
            task.add_done_callback(self._dying_tasks.discard)
            
        cleanup_session(session_id)

    async def stop(self):
        await super().stop()
        # Cancel and await all active session tasks
        for task in list(self._session_tasks.values()):
            if not task.done():
                task.cancel()
        if self._session_tasks:
            await asyncio.gather(*self._session_tasks.values(), return_exceptions=True)
        self._session_tasks.clear()
        
        # Await any remaining dying tasks to ensure clean termination
        if self._dying_tasks:
            await asyncio.gather(*self._dying_tasks, return_exceptions=True)
        self._dying_tasks.clear()
        self._session_queues.clear()

    def get_spoken_duration(self, session_id: str) -> float:
        return self._spoken_duration.get(session_id, 0.0)

    def reset_spoken_duration(self, session_id: str):
        self._spoken_duration[session_id] = 0.0

    async def _process_session(self, session_id: str):
        """Dedicated async loop per session. Blocks on this client's queue writes
        without affecting other sessions."""
        import struct
        q_internal = self._session_queues.get(session_id)
        if not q_internal:
            return
            
        while not self._cancel_event.is_set():
            try:
                chunk = await q_internal.get()
            except asyncio.CancelledError:
                break
                
            try:
                tok = get_cancel_token(chunk.session_id)
                if tok.is_cancelled:
                    logger.log("playback_skipped_cancelled", chunk.session_id, str(chunk.turn_id), detail={})
                    self._playback_started.pop(chunk.session_id, None)
                    continue

                if isinstance(chunk, AudioChunk):
                    current_turn = get_current_turn(chunk.session_id)
                    if chunk.turn_id < current_turn:
                        logger.log("playback_skipped_stale_turn", chunk.session_id,
                                   str(chunk.turn_id),
                                   detail={"current_turn": current_turn})
                        self._playback_started.pop(chunk.session_id, None)
                        continue

                q_client = self._clients.get(chunk.session_id)
                if q_client:
                    # Write block using standard await (safe backpressure)
                    if isinstance(chunk, AudioChunk) and chunk.data:
                        if chunk.session_id not in self._playback_started:
                            self._playback_started[chunk.session_id] = time.time()
                            telemetry_bus.push("playback_start", {}, chunk.session_id, str(chunk.turn_id))
                        chunk_duration = len(chunk.data) / 48000.0
                        self._spoken_duration[chunk.session_id] = self._spoken_duration.get(chunk.session_id, 0.0) + chunk_duration
                        tagged = struct.pack("<I", chunk.turn_id) + chunk.data
                        await q_client.put(tagged)
                    elif isinstance(chunk, AudioChunk) and chunk.is_last:
                        await q_client.put(struct.pack("<I", chunk.turn_id))
                    elif isinstance(chunk, TextResponse):
                        await q_client.put({
                            "type": "llm_response",
                            "text": chunk.text,
                            "turn_id": chunk.turn_id,
                            "tokens": chunk.tokens,
                            "latency_ms": chunk.latency_ms
                        })

                if isinstance(chunk, AudioChunk) and chunk.is_last:
                    start_time = self._playback_started.pop(chunk.session_id, None)
                    telemetry_bus.push("playback_end", {}, chunk.session_id, str(chunk.turn_id))
                    if start_time:
                        total_latency_ms = int((time.time() - start_time) * 1000)
                        telemetry_bus.push("turn_complete", {"total_latency_ms": total_latency_ms}, chunk.session_id, str(chunk.turn_id))
                    
                    pipeline = get_pipeline()
                    if pipeline and pipeline.fsm and hasattr(pipeline.fsm, "playback_done_input") and pipeline.fsm.playback_done_input:
                        pipeline.fsm.playback_done_input.put_nowait(
                            PlaybackDoneMessage(session_id=chunk.session_id, turn_id=chunk.turn_id)
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.log_error("playback_worker_session_error", chunk.session_id, str(chunk.turn_id), e)
                telemetry_bus.push("error", {"message": f"Playback Stage Session Error: {str(e)}"}, chunk.session_id, str(chunk.turn_id))
            finally:
                q_internal.task_done()

    async def run(self):
        """Global non-blocking distributor loop. Reads from global self.input
        and puts into session-specific queues instantly."""
        while not self._cancel_event.is_set():
            try:
                chunk = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            q_session = self._session_queues.get(chunk.session_id)
            if q_session:
                q_session.put_nowait(chunk)
            self.input.task_done()


# ---------------------------------------------------------------------------
# FSM Worker — orchestrates the conversation turn flow
# ---------------------------------------------------------------------------

class FSMWorker(PipelineStage):
    def __init__(self):
        super().__init__("fsm")
        self.transcript_input: asyncio.Queue = asyncio.Queue()
        self.llm_input: asyncio.Queue = asyncio.Queue()
        self.llm_output: asyncio.Queue = asyncio.Queue()
        self.tts_input: asyncio.Queue = asyncio.Queue()
        self.cancel_input: asyncio.Queue = asyncio.Queue()
        self.metrics_output: asyncio.Queue = asyncio.Queue()
        self.word_input: asyncio.Queue = asyncio.Queue()
        self.playback_done_input: asyncio.Queue = asyncio.Queue()
        self.playback_input: asyncio.Queue | None = None
        self._sessions: dict[str, _SessionState] = {}
        self._pending_responses: dict[tuple[str, int], dict] = {}

    async def _queue_consumer(self, q: asyncio.Queue, kind: str):
        while not self._cancel_event.is_set():
            try:
                item = await q.get()
                await self._funnel.put((kind, item))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.log("fsm_consumer_error", "system", "system", detail={"error": str(e), "kind": kind})
                err_msg = str(e).lower()
                is_loop_error = "different event loop" in err_msg or "loop is closed" in err_msg
                if isinstance(e, RuntimeError) and is_loop_error:
                    break
                await asyncio.sleep(0.1)

    async def run(self):
        self._funnel = asyncio.Queue()
        # Start long-lived consumer tasks
        consumers = [
            asyncio.create_task(self._queue_consumer(self.transcript_input, "transcript")),
            asyncio.create_task(self._queue_consumer(self.llm_output, "llm_response")),
            asyncio.create_task(self._queue_consumer(self.cancel_input, "cancel")),
            asyncio.create_task(self._queue_consumer(self.word_input, "word")),
            asyncio.create_task(self._queue_consumer(self.playback_done_input, "playback_done")),
        ]
        try:
            while not self._cancel_event.is_set():
                try:
                    kind, msg = await asyncio.wait_for(self._funnel.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue

                if self._cancel_event.is_set():
                    break

                try:
                    if kind == "transcript":
                        await self._handle_transcript(msg)
                    elif kind == "llm_response":
                        await self._handle_llm_response(msg)
                    elif kind == "cancel":
                        await self._handle_cancel(msg)
                    elif kind == "word":
                        await self._handle_word(msg)
                    elif kind == "playback_done":
                        await self._handle_playback_done(msg)
                except Exception as e:
                    logger.log("fsm_error", getattr(msg, "session_id", "system"), str(getattr(msg, "turn_id", "?")),
                               detail={"error": str(e)})
                    telemetry_bus.push("error", {"message": f"FSM Stage Error: {str(e)}"}, getattr(msg, "session_id", "system"), str(getattr(msg, "turn_id", "system")))
        finally:
            # Cancel and clean up all consumer tasks
            for c in consumers:
                if not c.done():
                    c.cancel()
            await asyncio.gather(*consumers, return_exceptions=True)


    async def _handle_transcript(self, msg: TranscriptMessage):
        logger.log("fsm_transcript_received", msg.session_id, str(getattr(msg, "turn_id", "0")),
                   detail={"text": msg.text[:80]})
                   
        # Reject transcripts if the client has already disconnected
        if hasattr(self, "playback") and self.playback:
            if msg.session_id not in self.playback._clients:
                logger.log("fsm_discard_disconnected_session", msg.session_id, str(msg.turn_id),
                           detail={"msg": "Discarding transcript: client already disconnected"})
                return

        state = self._get_session(msg.session_id)
        
        # Cleanup/eviction of any stray/pending entries from the previous turn
        prev_turn_key = (msg.session_id, state.turn_id)
        if prev_turn_key in self._pending_responses:
            entry = self._pending_responses[prev_turn_key]
            if entry["status"] == "pending":
                # Clean up / resolve as interrupted
                entry["status"] = "interrupted"
                # Evaluate spoken words and write a truncated turn if any was spoken
                spoken = getattr(state, "spoken_words", [])
                full_reply_words = entry["text"].split()
                if not spoken:
                    # Fallback to timing-based approximation
                    spoken_duration = 0.0
                    if hasattr(self, "playback") and self.playback:
                        spoken_duration = self.playback.get_spoken_duration(msg.session_id)
                    words_spoken_count = int(spoken_duration * 2.3)
                    if spoken_duration > 0.0 and words_spoken_count == 0:
                        words_spoken_count = 1
                    words_spoken_count = min(words_spoken_count, len(full_reply_words))
                    spoken = full_reply_words[:words_spoken_count]
                else:
                    num_spoken = min(len(spoken), len(full_reply_words))
                    spoken = full_reply_words[:num_spoken]

                if spoken:
                    from services.orchestrator.state_store import save_turn
                    save_turn(msg.session_id, str(state.turn_id), "assistant", " ".join(spoken))
            # Delete old entries for this session to prevent unbounded dict growth
            keys_to_del = [k for k in self._pending_responses.keys() if k[0] == msg.session_id and k[1] <= state.turn_id]
            for k in keys_to_del:
                self._pending_responses.pop(k, None)

        state.turn_id += 1
        set_current_turn(msg.session_id, state.turn_id)  # advance turn barrier before any LLM/TTS work
        turn_str = str(state.turn_id)



        # Check if this turn was an interruption of a previous assistant reply
        is_interrupted = state.interrupted
        state.interrupted = False  # Reset for the new turn

        if is_interrupted:
            from services.orchestrator.interruption_intelligence import interruption_intel
            
            # Evaluate using interruption intel
            intel_res = interruption_intel.evaluate_interruption(
                transcript=msg.text,
                stt_confidence=1.0,
                speech_duration_ms=vc_get("interruption.min_speech_duration_ms", 300),
                assistant_speaking_time_ms=1000,
                fsm_state="speaking",
                is_final=True,
                context={"session_id": msg.session_id, "turn_id": msg.turn_id}
            )
            decision = intel_res["decision"]
            category = intel_res["category"]
            
            logger.log(
                event_name="interruption_decision_logged",
                session_id=msg.session_id,
                turn_id=turn_str,
                detail={
                    "transcript": msg.text,
                    "category": category,
                    "decision": decision,
                    "reason": intel_res.get("reason", "")
                }
            )

            # Compute spoken and unspoken words
            spoken = getattr(state, "spoken_words", [])
            full_reply_words = state.current_reply.split()
            if not spoken:
                # Fallback to timing-based approximation
                spoken_duration = 0.0
                if hasattr(self, "playback") and self.playback:
                    spoken_duration = self.playback.get_spoken_duration(msg.session_id)
                words_spoken_count = int(spoken_duration * 2.3)
                words_spoken_count = min(words_spoken_count, len(full_reply_words))
                spoken = full_reply_words[:words_spoken_count]
            else:
                num_spoken = min(len(spoken), len(full_reply_words))
                spoken = full_reply_words[:num_spoken]

            unspoken = full_reply_words[len(spoken):]

            # 1. Context Merge Resolution (Revoke / correct assistant's last turn in history)
            from services.orchestrator.context_merge import resolve
            res = resolve(msg.session_id, spoken, unspoken, category)
            if res["strategy"] == "clarification":
                state.resume_text = " ".join(unspoken)

            # 2. Tool Interruption Policy Notification
            from services.orchestrator.tools import tool_manager
            tool_manager.on_interruption_during_call(msg.session_id, category)

            # Clear spoken words for the new turn
            state.spoken_words = []

            # If decision is abort, stop now and don't generate response
            if decision == "ABORT_ALL":
                return

        # Clear spoken words list for the new turn
        state.spoken_words = []

        # Reset spoken duration and current reply for the new turn
        if hasattr(self, "playback") and self.playback:
            self.playback.reset_spoken_duration(msg.session_id)
        state.current_reply = ""

        # INTENTIONAL DUAL-WRITE RESET: We reset both mechanisms together.
        # The streaming LLM client (groq/openai) checks cancellation_manager directly,
        # while the async pipeline stages check and propagate CancelToken.
        #
        # BUG FIX: Yield one event-loop tick BEFORE clearing the cancel flag.
        # Previously, the reset happened synchronously on the same tick as the
        # interruption signal, so in-flight LLM/TTS executor threads for the old
        # turn still saw is_cancelled=False and continued processing Question A
        # instead of stopping. The await gives those threads one cycle to observe
        # the cancellation before we clear it for the new turn.
        await asyncio.sleep(0)
        reset_cancel_token(msg.session_id)
        from services.orchestrator.cancellation_manager import cancellation_manager
        cancellation_manager.reset_session(msg.session_id)

        from services.orchestrator.state_store import load_history, save_turn
        history = load_history(msg.session_id)
        
        # Inject resume context if present
        if state.resume_text:
            history.append({
                "role": "system",
                "content": f"Note: The user interrupted your previous response. After addressing the user's latest query, please resume/incorporate the following unspoken points: {state.resume_text}"
            })
            state.resume_text = ""

        history.append({"role": "user", "content": msg.text})
        save_turn(msg.session_id, turn_str, "user", msg.text)

        telemetry_bus.push("llm_request", {"text": msg.text[:80]}, msg.session_id, turn_str)
        logger.log("fsm_llm_request_sent", msg.session_id, turn_str, detail={})

        # Detect if user explicitly requested a detailed or thorough answer
        user_text_lower = msg.text.lower()
        detail_keywords = ["detailed", "detail", "explain in depth", "tell me more", "explain more", "thorough", "elaborate"]
        is_detail_requested = any(kw in user_text_lower for kw in detail_keywords)
        
        max_tokens_override = None
        max_sentences_override = None
        if is_detail_requested:
            max_tokens_override = 400
            max_sentences_override = 6
            logger.log("fsm_detailed_mode_triggered", msg.session_id, turn_str,
                       detail={"max_tokens": 400, "max_sentences": 6})

        await self.llm_input.put(LLMRequest(
            messages=history,
            session_id=msg.session_id,
            turn_id=state.turn_id,
            max_tokens=max_tokens_override,
            max_sentences=max_sentences_override,
        ))

    async def _handle_llm_response(self, msg):
        """Route LLMSentenceChunk (sentence-level pipelining) or legacy LLMResponse."""
        if isinstance(msg, LLMSentenceChunk):
            await self._handle_llm_sentence(msg)
        else:
            # Legacy LLMResponse path — kept for any future callers that bypass
            # call_primary_streaming (e.g. direct error injection in tests).
            logger.log("fsm_llm_response_received", msg.session_id, str(msg.turn_id),
                       detail={"text": msg.text[:60]})
            state = self._get_session(msg.session_id)
            state.current_reply = msg.text
            self._pending_responses[(msg.session_id, msg.turn_id)] = {
                "text": msg.text, "status": "pending"
            }
            logger.log("fsm_sending_to_tts", msg.session_id, str(msg.turn_id), detail={})
            await self.tts_input.put(TTSRequest(
                text=msg.text, session_id=msg.session_id, turn_id=msg.turn_id,
                is_final_sentence=True))
            if hasattr(self, "playback_input") and self.playback_input:
                await self.playback_input.put(TextResponse(
                    text=msg.text, session_id=msg.session_id, turn_id=msg.turn_id,
                    tokens=msg.tokens, latency_ms=msg.latency_ms))
            await self.metrics_output.put(MetricsEvent(
                "turn_complete", msg.session_id, str(msg.turn_id),
                {"reply": msg.text[:60], "tokens": msg.tokens}))

    async def _handle_llm_sentence(self, msg: LLMSentenceChunk):
        """Handle one sentence from the streaming LLM pipeline."""
        state = self._get_session(msg.session_id)

        # Accumulate reply text sentence by sentence
        sep = " " if state.current_reply else ""
        state.current_reply += sep + msg.text

        turn_key = (msg.session_id, msg.turn_id)

        # Upsert pending-response entry on EVERY sentence so that _handle_cancel
        # always has the dispatched-so-far text even if interrupted before is_final.
        if turn_key not in self._pending_responses:
            self._pending_responses[turn_key] = {
                "text": state.current_reply, "status": "pending"
            }
        elif self._pending_responses[turn_key]["status"] == "pending":
            self._pending_responses[turn_key]["text"] = state.current_reply

        # Skip TTS for empty text unless it's the final terminal signal
        if msg.text or msg.is_final:
            logger.log("fsm_sending_to_tts", msg.session_id, str(msg.turn_id),
                       detail={"sentence_idx": msg.sentence_index, "is_final": msg.is_final})
            await self.tts_input.put(TTSRequest(
                text=msg.text,
                session_id=msg.session_id,
                turn_id=msg.turn_id,
                is_final_sentence=msg.is_final,
            ))

        if msg.is_final:
            # Use full_reply_text from LLMWorker as the authoritative full text.
            full_text = msg.full_reply_text or state.current_reply
            if self._pending_responses[turn_key]["status"] == "pending":
                self._pending_responses[turn_key]["text"] = full_text

            if hasattr(self, "playback_input") and self.playback_input:
                await self.playback_input.put(TextResponse(
                    text=full_text, session_id=msg.session_id, turn_id=msg.turn_id,
                    tokens=msg.tokens, latency_ms=msg.latency_ms))

            logger.log("fsm_llm_sentences_complete", msg.session_id, str(msg.turn_id),
                       detail={"sentences": msg.sentence_index + 1, "tokens": msg.tokens})
            await self.metrics_output.put(MetricsEvent(
                "turn_complete", msg.session_id, str(msg.turn_id),
                {"reply": full_text[:60], "tokens": msg.tokens}))

    async def _handle_cancel(self, msg: CancelCommand):
        # INTENTIONAL DUAL-WRITE CANCEL: We update both mechanisms on cancellation.
        # The streaming LLM client (groq/openai) checks cancellation_manager directly,
        # while the async pipeline stages check and propagate CancelToken.
        tok = get_cancel_token(msg.session_id)
        tok.cancel(msg.reason)
        from services.orchestrator.cancellation_manager import cancellation_manager
        cancellation_manager.cancel_session(msg.session_id, msg.reason)

        telemetry_bus.push("cancellation", {"reason": msg.reason},
                             msg.session_id, "system")
        await self.metrics_output.put(MetricsEvent(
            "cancellation", msg.session_id, "system", {"reason": msg.reason}))

        state = self._get_session(msg.session_id)
        state.interrupted = True

        norm_reason = msg.reason.lower().replace("-", "_")
        if norm_reason in ("correction", "topic_change", "clarification", "stop_cancel", "add_on"):
            interruption_type = norm_reason
        else:
            interruption_type = "stop_cancel"

        # IDEMPOTENCY RULE: Transition the pending response status to cancelled
        # only if it is currently in 'pending' state.
        turn_key = (msg.session_id, state.turn_id)
        if turn_key in self._pending_responses:
            entry = self._pending_responses[turn_key]
            if entry["status"] == "pending":
                entry["status"] = "cancelled"
                
                # Check spoken words vs timing-based approximation
                spoken = getattr(state, "spoken_words", [])
                full_reply_words = entry["text"].split()
                if not spoken:
                    spoken_duration = 0.0
                    if hasattr(self, "playback") and self.playback:
                        spoken_duration = self.playback.get_spoken_duration(msg.session_id)
                    words_spoken_count = int(spoken_duration * 2.3)
                    if spoken_duration > 0.0 and words_spoken_count == 0:
                        words_spoken_count = 1
                    words_spoken_count = min(words_spoken_count, len(full_reply_words))
                    spoken = full_reply_words[:words_spoken_count]
                else:
                    num_spoken = min(len(spoken), len(full_reply_words))
                    spoken = full_reply_words[:num_spoken]

                # Commit ONLY the spoken segment to history (never commit the full text)
                if spoken:
                    from services.orchestrator.state_store import save_turn
                    save_turn(msg.session_id, str(state.turn_id), "assistant", " ".join(spoken))

        from services.orchestrator.tools import tool_manager
        tool_manager.on_interruption_during_call(msg.session_id, interruption_type)

    async def _handle_playback_done(self, msg: PlaybackDoneMessage):
        # IDEMPOTENCY RULE: Commit response to history only if still pending.
        # This prevents double resolution if cancel and complete signals arrive close together.
        turn_key = (msg.session_id, msg.turn_id)
        if turn_key in self._pending_responses:
            entry = self._pending_responses[turn_key]
            if entry["status"] == "pending":
                entry["status"] = "completed"
                from services.orchestrator.state_store import save_turn
                save_turn(msg.session_id, str(msg.turn_id), "assistant", entry["text"])

    async def _handle_word(self, msg: WordMessage):
        state = self._get_session(msg.session_id)
        if not hasattr(state, "spoken_words"):
            state.spoken_words = []
        state.spoken_words.append(msg.word)

    def _get_session(self, session_id: str):
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionState()
        return self._sessions[session_id]

    def get_session_turn_id(self, session_id: str) -> int:
        """Return the current turn_id for a session, or 0 if not yet started.
        Used by api_gateway to tag stop_audio messages with the active turn."""
        state = self._sessions.get(session_id)
        return state.turn_id if state else 0

    def cleanup_session(self, session_id: str) -> None:
        """Remove all FSMWorker per-session state for a disconnected session.
        Leaves _pending_responses entries for any turns still in flight so
        that in-progress commits complete normally; only removes the session
        slot and old completed entries."""
        self._sessions.pop(session_id, None)
        # Remove completed/cancelled entries for this session
        stale_keys = [
            k for k in list(self._pending_responses.keys())
            if k[0] == session_id and self._pending_responses[k]["status"] != "pending"
        ]
        for k in stale_keys:
            self._pending_responses.pop(k, None)

class _SessionState:
    def __init__(self):
        self.turn_id = 0
        self.current_reply = ""
        self.resume_text = ""
        self.spoken_words = []
        self.interrupted = False

# ---------------------------------------------------------------------------
# Interrupt Monitor Worker
# ---------------------------------------------------------------------------

class InterruptMonitorWorker(PipelineStage):
    def __init__(self):
        super().__init__("interrupt_monitor")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()

    async def run(self):
        while not self._cancel_event.is_set():
            try:
                event = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            try:
                if event.kind in ("vad_start", "barge_in"):
                    tok = get_cancel_token(event.session_id)
                    if not tok.is_cancelled:
                        # INTENTIONAL DUAL-WRITE CANCEL: We update both mechanisms on cancellation.
                        # The streaming LLM client (groq/openai) checks cancellation_manager directly,
                        # while the async pipeline stages check and propagate CancelToken.
                        tok.cancel(event.kind)
                        from services.orchestrator.cancellation_manager import cancellation_manager
                        cancellation_manager.cancel_session(event.session_id, event.kind)
                        
                        telemetry_bus.push("vad_start", {}, event.session_id, "system")
                        await self.output.put(CancelCommand(event.session_id, event.kind))
                elif event.kind == "stop_button":
                    # INTENTIONAL DUAL-WRITE CANCEL: We update both mechanisms on cancellation.
                    tok = get_cancel_token(event.session_id)
                    tok.cancel("stop_button")
                    from services.orchestrator.cancellation_manager import cancellation_manager
                    cancellation_manager.cancel_session(event.session_id, "stop_button")
                    
                    await self.output.put(CancelCommand(event.session_id, "stop_button"))
            except Exception as e:
                logger.log_error("interrupt_monitor_worker_error", getattr(event, "session_id", "system"), "system", e)
                telemetry_bus.push("error", {"message": f"Interrupt Monitor Error: {str(e)}"}, getattr(event, "session_id", "system"), "system")

# Note: CancellationWorker was removed. We rely on cooperative CancelToken checks
# inside streaming loops (Groq, OpenAI, Cartesia) and workers (LLM, TTS, Playback)
# to discard stale chunks and stop executions. Since Python executor thread-pool
# futures cannot be aborted once running, cooperative checks are the only way
# to prevent mid-flight generation.

# ---------------------------------------------------------------------------
# Metrics Worker — pushes to telemetry bus
# ---------------------------------------------------------------------------

class MetricsWorker(PipelineStage):
    def __init__(self):
        super().__init__("metrics")
        self.input: asyncio.Queue = asyncio.Queue()

    async def run(self):
        while not self._cancel_event.is_set():
            try:
                ev = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            try:
                telemetry_bus.push(ev.event_type, ev.data, ev.session_id, ev.turn_id)
            except Exception as e:
                logger.log_error("metrics_worker_error", getattr(ev, "session_id", "system"), "system", e)

# ---------------------------------------------------------------------------
# Pipeline orchestrator — wires all workers together
# ---------------------------------------------------------------------------

class VoicePipeline:
    """Top-level orchestrator that creates, connects, and manages all workers."""

    def __init__(self):
        self.stt = STTWorker()
        self.llm = LLMWorker()
        self.tts = TTSWorker()
        self.playback = PlaybackWorker()
        self.fsm = FSMWorker()
        self.interrupt = InterruptMonitorWorker()
        self.metrics = MetricsWorker()
        self._started = False

    def start(self):
        if self._started:
            return
        
        # Instantiate queues inside active loop
        global _main_loop
        _main_loop = asyncio.get_running_loop()
        self.stt.input = asyncio.Queue()
        self.stt.output = asyncio.Queue()
        self.llm.input = asyncio.Queue()
        self.llm.output = asyncio.Queue()
        self.tts.input = asyncio.Queue()
        self.tts.output = asyncio.Queue()
        self.playback.input = asyncio.Queue()
        self.fsm.transcript_input = asyncio.Queue()
        self.fsm.word_input = asyncio.Queue()
        self.fsm.playback_done_input = asyncio.Queue()
        self.fsm.llm_input = asyncio.Queue()
        self.fsm.llm_output = asyncio.Queue()
        self.fsm.tts_input = asyncio.Queue()
        self.fsm.cancel_input = asyncio.Queue()
        self.fsm.metrics_output = asyncio.Queue()
        self.interrupt.input = asyncio.Queue()
        self.interrupt.output = asyncio.Queue()
        self.metrics.input = asyncio.Queue()

        logger.log_service_start("voice-pipeline", detail={"workers": 7})
        # Wire queues: STT → FSM
        self.stt.output = self.fsm.transcript_input
        # Wire queues: FSM → LLM
        self.fsm.llm_input = self.llm.input
        # Wire queues: LLM → FSM (for response routing)
        self.llm.output = self.fsm.llm_output
        # Wire queues: FSM → TTS
        self.fsm.tts_input = self.tts.input
        # Wire queues: TTS → Playback
        self.tts.output = self.playback.input
        # Wire queues: Interrupt → FSM (cancel)
        self.interrupt.output = self.fsm.cancel_input
        # Wire queues: FSM → Metrics
        self.fsm.metrics_output = self.metrics.input
        # Wire queues: FSM → Playback (for text responses)
        self.fsm.playback_input = self.playback.input
        self.fsm.playback = self.playback

        for stage in [self.stt, self.llm, self.tts, self.playback,
                      self.fsm, self.interrupt, self.metrics]:
            stage.start()

        self._started = True

    async def stop(self):
        logger.log_service_stop("voice-pipeline", detail={"reason": "shutdown"})
        for stage in [self.stt, self.llm, self.tts, self.playback,
                      self.fsm, self.interrupt, self.metrics]:
            await stage.stop()
        self._started = False

    async def submit_transcript(self, session_id: str, text: str, turn_id: int = 0):
        await self.stt.input.put(TranscriptMessage(
            text=text, session_id=session_id, turn_id=turn_id))

    async def submit_interrupt(self, session_id: str, kind: str):
        await self.interrupt.input.put(InterruptEvent(
            session_id=session_id, kind=kind))

    async def submit_cancel(self, session_id: str, reason: str):
        await self.fsm.cancel_input.put(CancelCommand(
            session_id=session_id, reason=reason))

    def register_playback_client(self, session_id: str, queue: asyncio.Queue):
        self.playback.register_client(session_id, queue)

    def unregister_playback_client(self, session_id: str):
        self.playback.unregister_client(session_id)
        
        # Pop and cancel any remaining LLM/TTS session tasks
        llm_task = self.llm._session_tasks.pop(session_id, None)
        if llm_task and not llm_task.done():
            llm_task.cancel()
        tts_task = self.tts._session_tasks.pop(session_id, None)
        if tts_task and not tts_task.done():
            tts_task.cancel()
            
        # Also clean up FSMWorker per-session state (completed/cancelled entries only)
        self.fsm.cleanup_session(session_id)

    def register_task(self, session_id: str, task: asyncio.Task):
        pass


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_main_loop = None
_pipeline: VoicePipeline | None = None


def get_pipeline() -> VoicePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = VoicePipeline()
    return _pipeline


async def shutdown_pipeline():
    global _pipeline
    if _pipeline:
        await _pipeline.stop()
        _pipeline = None
