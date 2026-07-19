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
class TTSRequest:
    text: str
    session_id: str
    turn_id: int

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
                tok = get_cancel_token(msg.session_id)
                if tok.is_cancelled:
                    continue

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

            logger.log("llm_request_received", req.session_id, str(req.turn_id),
                       detail={"messages": len(req.messages)})
            settings = get_settings()
            api_key = settings.groq_api_key
            if not api_key or api_key == "dummy_val" or settings.env == "test":
                await asyncio.sleep(vc_get("llm.mock_sleep_ms", 50) / 1000.0)
                telemetry_bus.push("llm_first_token", {"latency_ms": vc_get("llm.mock_sleep_ms", 50)},
                                   req.session_id, str(req.turn_id))
                last = req.messages[-1]["content"].lower() if req.messages else ""
                if "mars" in last:
                    reply = "Mars is the fourth planet from the Sun."
                elif "far" in last or "distance" in last:
                    context_has = any("mars" in m.get("content", "").lower() for m in req.messages[:-1])
                    reply = "It is about 225 million km away." if context_has else "Distance to what?"
                else:
                    reply = "You're welcome!"
                telemetry_bus.push("llm_complete", {"latency_ms": 50},
                                   req.session_id, str(req.turn_id))
                logger.log("llm_mock_response", req.session_id, str(req.turn_id),
                           detail={"reply": reply[:60]})
                await self.output.put(LLMResponse(
                    text=reply, session_id=req.session_id,
                    turn_id=req.turn_id, tokens=len(reply.split()), latency_ms=50))
                continue

            logger.log("llm_real_call_start", req.session_id, str(req.turn_id),
                       detail={"model": settings.groq_model})
            loop = asyncio.get_event_loop()
            system_prompt = vc_get("llm.system_prompt", "You are a helpful, concise voice assistant.")
            context_history = prepare_context(req.messages, req.session_id)
            payload = [{"role": "system", "content": system_prompt}] + context_history

            budget = get_token_budget(req.session_id)

            t0 = time.time()
            try:
                try:
                    reply_text, token_count = await loop.run_in_executor(
                        None, self._llm_sync, api_key, settings.groq_model, payload, loop, req.session_id, req.turn_id)
                    provider = "groq"
                except Exception as e:
                    logger.log("llm_real_call_failed", req.session_id, str(req.turn_id),
                               detail={"error": str(e)})
                    fallback_key = settings.openai_api_key
                    if fallback_key and fallback_key != "dummy_val":
                        logger.log("llm_failover_triggered", req.session_id, str(req.turn_id),
                                   detail={"reason": str(e), "model": settings.openai_fallback_model})
                        telemetry_bus.push("llm_failover_triggered", {"reason": str(e)}, req.session_id, str(req.turn_id))
                        reply_text, token_count = await loop.run_in_executor(
                            None, self._openai_fallback_sync, fallback_key, settings.openai_fallback_model, payload, loop, req.session_id, req.turn_id)
                        provider = "openai"
                    else:
                        raise e

                latency_ms = int((time.time() - t0) * 1000)
                budget.record_prompt(sum(len(m.get("content", "")) // 4 + 3 for m in payload))
                budget.record_completion(token_count)

                telemetry_bus.push("llm_complete", {"latency_ms": latency_ms,
                                   "prompt_tokens": budget.prompt_tokens,
                                   "completion_tokens": token_count,
                                   "provider": provider},
                                   req.session_id, str(req.turn_id))
                logger.log("llm_real_response", req.session_id, str(req.turn_id),
                           detail={"tokens": token_count, "reply": reply_text[:60], "provider": provider})
                await self.output.put(LLMResponse(
                    text=reply_text, session_id=req.session_id,
                    turn_id=req.turn_id, tokens=token_count, latency_ms=latency_ms))

            except Exception as outer_err:
                logger.log_error("llm_worker_processing_failed", req.session_id, str(req.turn_id), outer_err)
                telemetry_bus.push("error", {"message": f"LLM Stage Error: {str(outer_err)}"}, req.session_id, str(req.turn_id))
                # Send error response so pipeline does not hang
                await self.output.put(LLMResponse(
                    text="I'm sorry, I encountered an LLM error.", session_id=req.session_id,
                    turn_id=req.turn_id, tokens=0))

    def _llm_sync(self, api_key: str, model: str, payload: list[dict], loop: asyncio.AbstractEventLoop, session_id: str, turn_id: int) -> tuple[str, int]:
        from groq import Groq
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(messages=payload, model=model, stream=True)
        tokens = 0
        chunks = []
        start_time = time.time()
        first_token_fired = False
        for chunk in completion:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                if not first_token_fired:
                    first_token_fired = True
                    latency_ms = int((time.time() - start_time) * 1000)
                    loop.call_soon_threadsafe(telemetry_bus.push, "llm_first_token", {"latency_ms": latency_ms}, session_id, str(turn_id))
                chunks.append(delta)
                tokens += 1
        return "".join(chunks), tokens

    def _openai_fallback_sync(self, api_key: str, model: str, payload: list[dict], loop: asyncio.AbstractEventLoop, session_id: str, turn_id: int) -> tuple[str, int]:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(messages=payload, model=model, stream=True)
        tokens = 0
        chunks = []
        start_time = time.time()
        first_token_fired = False
        for chunk in completion:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                if not first_token_fired:
                    first_token_fired = True
                    latency_ms = int((time.time() - start_time) * 1000)
                    loop.call_soon_threadsafe(telemetry_bus.push, "llm_first_token", {"latency_ms": latency_ms}, session_id, str(turn_id))
                chunks.append(delta)
                tokens += 1
        return "".join(chunks), tokens

# ---------------------------------------------------------------------------
# TTS Worker
# ---------------------------------------------------------------------------

class TTSWorker(PipelineStage):
    def __init__(self):
        super().__init__("tts")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()

    async def run(self):
        while not self._cancel_event.is_set():
            try:
                req = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            try:
                logger.log("tts_request_received", req.session_id, str(req.turn_id),
                           detail={"text": req.text[:60]})

                tok = get_cancel_token(req.session_id)
                if tok.is_cancelled:
                    logger.log("tts_skipped_cancelled", req.session_id, str(req.turn_id), detail={})
                    continue

                settings = get_settings()
                api_key = settings.cartesia_api_key
                mock = not api_key or api_key == "dummy_val" or settings.env == "test"
                logger.log("tts_starting", req.session_id, str(req.turn_id),
                           detail={"mock": mock})

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, self._tts_sync, api_key, req, mock, loop)
            except Exception as e:
                logger.log_error("tts_worker_processing_failed", req.session_id, str(req.turn_id), e)
                telemetry_bus.push("error", {"message": f"TTS Stage Error: {str(e)}"}, req.session_id, str(req.turn_id))
                # Push dummy end chunk to prevent client hanging
                await self.output.put(AudioChunk(b"", req.session_id, req.turn_id, True))

    def _tts_sync(self, api_key: str, req: TTSRequest, mock: bool, loop: asyncio.AbstractEventLoop):
        def _put(chunk: AudioChunk):
            asyncio.run_coroutine_threadsafe(self.output.put(chunk), loop)

        start_time = time.time()
        loop.call_soon_threadsafe(telemetry_bus.push, "tts_start", {"sentence_idx": 0}, req.session_id, str(req.turn_id))

        if mock:
            time.sleep(vc_get("tts.mock_sleep_ms", 50) / 1000.0)
            silence = vc_get("tts.mock_chunk_silence_bytes", 16000)
            mock_wav = (
                b'RIFF\x24\x3e\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00'
                b'@\x1f\x00\x00\x80\x3e\x00\x00\x02\x00\x10\x00data\x00\x3e\x00\x00'
                + b'\x00' * silence
            )
            latency_ms = int((time.time() - start_time) * 1000)
            loop.call_soon_threadsafe(telemetry_bus.push, "tts_complete", {"latency_ms": latency_ms}, req.session_id, str(req.turn_id))
            _put(AudioChunk(mock_wav, req.session_id, req.turn_id, True))
            return

        from cartesia import Cartesia
        client = Cartesia(api_key=api_key)
        response = client.tts.bytes(
            model_id=vc_get("tts.model_id", "sonic-3.5"),
            transcript=req.text,
            voice={"mode": "id", "id": vc_get("tts.voice_id", "4459a9a5-69d6-4680-b970-e13dc51845b6")},
            language=vc_get("tts.language", "en"),
            output_format={
                "container": vc_get("tts.output_format.container", "wav"),
                "encoding": vc_get("tts.output_format.encoding", "pcm_s16le"),
                "sample_rate": vc_get("tts.output_format.sample_rate", 24000),
            }
        )

        if isinstance(response, bytes):
            loop.call_soon_threadsafe(telemetry_bus.push, "tts_chunk", {"sentence": req.text[:40]}, req.session_id, str(req.turn_id))
            _put(AudioChunk(response, req.session_id, req.turn_id, True))
        elif hasattr(response, "__iter__"):
            for chunk in response:
                loop.call_soon_threadsafe(telemetry_bus.push, "tts_chunk", {"sentence": req.text[:40]}, req.session_id, str(req.turn_id))
                _put(AudioChunk(chunk, req.session_id, req.turn_id, False))
            _put(AudioChunk(b"", req.session_id, req.turn_id, True))

        latency_ms = int((time.time() - start_time) * 1000)
        loop.call_soon_threadsafe(telemetry_bus.push, "tts_complete", {"latency_ms": latency_ms}, req.session_id, str(req.turn_id))

# ---------------------------------------------------------------------------
# Playback Worker — sends audio to WebSocket clients
# ---------------------------------------------------------------------------

class PlaybackWorker(PipelineStage):
    def __init__(self):
        super().__init__("playback")
        self.input: asyncio.Queue = asyncio.Queue()
        self._clients: dict[str, asyncio.Queue] = {}
        self._playback_started: dict[str, float] = {}  # session_id -> start_time

    def register_client(self, session_id: str, queue: asyncio.Queue):
        self._clients[session_id] = queue

    def unregister_client(self, session_id: str):
        self._clients.pop(session_id, None)

    async def run(self):
        while not self._cancel_event.is_set():
            try:
                chunk = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            try:
                q = self._clients.get(chunk.session_id)
                if q:
                    if isinstance(chunk, AudioChunk) and chunk.data:
                        if chunk.session_id not in self._playback_started:
                            self._playback_started[chunk.session_id] = time.time()
                            telemetry_bus.push("playback_start", {}, chunk.session_id, str(chunk.turn_id))
                        await q.put(chunk.data)
                    elif isinstance(chunk, TextResponse):
                        await q.put({
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
            except Exception as e:
                logger.log_error("playback_worker_error", chunk.session_id, str(chunk.turn_id), e)
                telemetry_bus.push("error", {"message": f"Playback Stage Error: {str(e)}"}, chunk.session_id, str(chunk.turn_id))

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
        self.playback_input: asyncio.Queue | None = None
        self._sessions: dict[str, _SessionState] = {}

    async def run(self):
        while not self._cancel_event.is_set():
            try:
                done, _ = await asyncio.wait(
                    [asyncio.create_task(j) for j in [
                        self._wait_queue(self.transcript_input, "transcript"),
                        self._wait_queue(self.llm_output, "llm_response"),
                        self._wait_queue(self.cancel_input, "cancel"),
                    ]],
                    timeout=0.5, return_when=asyncio.FIRST_COMPLETED
                )
                for coro in done:
                    try:
                        result = coro.result()
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        continue
                    if result is None:
                        continue
                    kind, msg = result
                    try:
                        if kind == "transcript":
                            await self._handle_transcript(msg)
                        elif kind == "llm_response":
                            await self._handle_llm_response(msg)
                        elif kind == "cancel":
                            await self._handle_cancel(msg)
                    except Exception as e:
                        logger.log("fsm_error", getattr(msg, "session_id", "system"), str(getattr(msg, "turn_id", "?")),
                                   detail={"error": str(e)})
                        telemetry_bus.push("error", {"message": f"FSM Stage Error: {str(e)}"}, getattr(msg, "session_id", "system"), str(getattr(msg, "turn_id", "system")))
            except Exception as outer_err:
                logger.log_error("fsm_worker_loop_error", "system", "system", outer_err)

    async def _wait_queue(self, q: asyncio.Queue, kind: str, timeout: float = 0.5):
        try:
            item = await asyncio.wait_for(q.get(), timeout=timeout)
            return kind, item
        except asyncio.TimeoutError:
            return None

    async def _handle_transcript(self, msg: TranscriptMessage):
        logger.log("fsm_transcript_received", msg.session_id, str(getattr(msg, "turn_id", "0")),
                   detail={"text": msg.text[:80]})
        state = self._get_session(msg.session_id)
        state.turn_id += 1
        turn_str = str(state.turn_id)

        from services.orchestrator.state_store import load_history, save_turn
        history = load_history(msg.session_id)
        history.append({"role": "user", "content": msg.text})
        save_turn(msg.session_id, turn_str, "user", msg.text)

        telemetry_bus.push("llm_request", {"text": msg.text[:80]}, msg.session_id, turn_str)
        logger.log("fsm_llm_request_sent", msg.session_id, turn_str, detail={})

        await self.llm_input.put(LLMRequest(
            messages=history, session_id=msg.session_id, turn_id=state.turn_id))

    async def _handle_llm_response(self, msg: LLMResponse):
        logger.log("fsm_llm_response_received", msg.session_id, str(msg.turn_id),
                   detail={"text": msg.text[:60]})
        from services.orchestrator.state_store import save_turn
        save_turn(msg.session_id, str(msg.turn_id), "assistant", msg.text)

        logger.log("fsm_sending_to_tts", msg.session_id, str(msg.turn_id), detail={})
        await self.tts_input.put(TTSRequest(
            text=msg.text, session_id=msg.session_id, turn_id=msg.turn_id))

        # Push LLM response text to playback worker so it goes to the WebSocket client
        if hasattr(self, "playback_input") and self.playback_input:
            await self.playback_input.put(TextResponse(
                text=msg.text, session_id=msg.session_id, turn_id=msg.turn_id,
                tokens=msg.tokens, latency_ms=msg.latency_ms))

        logger.log("fsm_sending_metrics", msg.session_id, str(msg.turn_id), detail={})
        await self.metrics_output.put(MetricsEvent(
            "turn_complete", msg.session_id, str(msg.turn_id),
            {"reply": msg.text[:60], "tokens": msg.tokens}))

    async def _handle_cancel(self, msg: CancelCommand):
        tok = get_cancel_token(msg.session_id)
        tok.cancel(msg.reason)
        telemetry_bus.push("cancellation", {"reason": msg.reason},
                           msg.session_id, "system")
        await self.metrics_output.put(MetricsEvent(
            "cancellation", msg.session_id, "system", {"reason": msg.reason}))

    def _get_session(self, session_id: str):
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionState()
        return self._sessions[session_id]

class _SessionState:
    def __init__(self):
        self.turn_id = 0

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
                        tok.cancel(event.kind)
                        telemetry_bus.push("vad_start", {}, event.session_id, "system")
                        await self.output.put(CancelCommand(event.session_id, event.kind))
                elif event.kind == "stop_button":
                    tok = get_cancel_token(event.session_id)
                    tok.cancel("stop_button")
                    await self.output.put(CancelCommand(event.session_id, "stop_button"))
            except Exception as e:
                logger.log_error("interrupt_monitor_worker_error", getattr(event, "session_id", "system"), "system", e)
                telemetry_bus.push("error", {"message": f"Interrupt Monitor Error: {str(e)}"}, getattr(event, "session_id", "system"), "system")

# ---------------------------------------------------------------------------
# Cancellation Manager Worker — cleans up tasks
# ---------------------------------------------------------------------------

class CancellationWorker(PipelineStage):
    def __init__(self):
        super().__init__("cancellation")
        self.input: asyncio.Queue = asyncio.Queue()
        self._active_tasks: dict[str, list[asyncio.Task]] = {}

    def register_task(self, session_id: str, task: asyncio.Task):
        self._active_tasks.setdefault(session_id, []).append(task)

    async def run(self):
        while not self._cancel_event.is_set():
            try:
                cmd = await asyncio.wait_for(self.input.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue

            if self._cancel_event.is_set():
                break

            try:
                tasks = self._active_tasks.pop(cmd.session_id, [])
                for t in tasks:
                    if not t.done():
                        t.cancel()
                telemetry_bus.push("cancellation", {"reason": cmd.reason,
                                   "tasks_cancelled": len(tasks)},
                                   cmd.session_id, "system")
            except Exception as e:
                logger.log_error("cancellation_worker_error", getattr(cmd, "session_id", "system"), "system", e)

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
        self.canceller = CancellationWorker()
        self.metrics = MetricsWorker()
        self._started = False

    def start(self):
        if self._started:
            return
        logger.log_service_start("voice-pipeline", detail={"workers": 8})
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

        for stage in [self.stt, self.llm, self.tts, self.playback,
                      self.fsm, self.interrupt, self.canceller, self.metrics]:
            stage.start()

        self._started = True

    async def stop(self):
        logger.log_service_stop("voice-pipeline", detail={"reason": "shutdown"})
        for stage in [self.stt, self.llm, self.tts, self.playback,
                      self.fsm, self.interrupt, self.canceller, self.metrics]:
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
        await self.canceller.input.put(CancelCommand(
            session_id=session_id, reason=reason))

    def register_playback_client(self, session_id: str, queue: asyncio.Queue):
        self.playback.register_client(session_id, queue)

    def unregister_playback_client(self, session_id: str):
        self.playback.unregister_client(session_id)

    def register_task(self, session_id: str, task: asyncio.Task):
        self.canceller.register_task(session_id, task)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

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
