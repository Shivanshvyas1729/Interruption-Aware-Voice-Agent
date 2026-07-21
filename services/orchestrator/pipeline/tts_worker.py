"""
pipeline/tts_worker.py — Text-to-Speech synthesis stage.

Accepts TTSRequest items (one per sentence), synthesises audio via Cartesia,
and emits AudioChunk items to the Playback worker.

Key design decisions:
  • Per-session task chaining preserves sentence ordering while allowing
    concurrent sessions to synthesise in parallel on a thread pool.
  • Shared per-turn WebSocket context (open_ws_context / speak_sentence_ws /
    close_ws_context) allows Cartesia's streaming continuation: all sentences
    in a turn share one WS so the voice prosody flows naturally.
  • Fallback path: if the API key is missing or continuation is unsupported,
    each sentence uses a fresh speak_stream_ws call.
  • On any failure or cancellation a terminal AudioChunk(is_last=True, data=b"")
    is always emitted so PlaybackWorker and FSMWorker never hang waiting.

Telemetry emitted (consistent across all paths):
  • tts_start         — when synthesis begins for a sentence
  • tts_chunk         — for each audio chunk received from Cartesia
  • tts_complete      — when the final sentence of a turn is done (normal path)
  • tts_skipped_cancelled       — early cancel check before queuing task
  • tts_skipped_cancelled_post_wait — cancel detected after prev-task await
  • tts_skipped_stale_turn      — turn_id older than current active turn
  • error             — on exception (all error paths)
"""

import asyncio
import time
from typing import Any
from common.config.settings import get_settings
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from .base import PipelineStage
from .messages import TTSRequest, AudioChunk
from .cancel_token import get_cancel_token, get_current_turn

logger = get_logger("async-pipeline")


class TTSWorker(PipelineStage):
    def __init__(self):
        super().__init__("tts")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()
        self._ws_sessions: dict[str, Any] = {}
        self._session_tasks: dict[str, asyncio.Task] = {}
        self.executor = None

    def start(self):
        from concurrent.futures import ThreadPoolExecutor
        from common.config import voice_settings
        max_workers = voice_settings.get("concurrency.tts_max_workers", 200)
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="tts_worker"
        )
        super().start()

    async def stop(self):
        await super().stop()
        if self.executor:
            self.executor.shutdown(wait=False)
        from services.orchestrator.tts_client import close_ws_context
        for turn_key, (ws, _) in list(self._ws_sessions.items()):
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

            tok = get_cancel_token(req.session_id)
            if tok.is_cancelled:
                logger.log(
                    "tts_skipped_cancelled", req.session_id, str(req.turn_id),
                    detail={},
                )
                continue

            current_turn = get_current_turn(req.session_id)
            if req.turn_id < current_turn:
                logger.log(
                    "tts_skipped_stale_turn", req.session_id, str(req.turn_id),
                    detail={"current_turn": current_turn},
                )
                continue

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

    async def _process_request(
        self, req: TTSRequest, prev_task: "asyncio.Task | None"
    ):
        if prev_task is not None:
            if not prev_task.done():
                try:
                    await prev_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.log_error(
                        "tts_prior_task_failed", req.session_id, str(req.turn_id), e
                    )
            else:
                if not prev_task.cancelled():
                    try:
                        exc = prev_task.exception()
                        if exc is not None:
                            logger.log_error(
                                "tts_prior_task_failed",
                                req.session_id, str(req.turn_id), exc,
                            )
                    except Exception:
                        pass

        tok = get_cancel_token(req.session_id)
        if tok.is_cancelled:
            logger.log(
                "tts_skipped_cancelled_post_wait",
                req.session_id, str(req.turn_id), detail={},
            )
            turn_key = f"{req.session_id}:{req.turn_id}"
            if turn_key in self._ws_sessions:
                from services.orchestrator.tts_client import close_ws_context
                ws, _ = self._ws_sessions.pop(turn_key)
                close_ws_context(ws, req.session_id, str(req.turn_id))
            return

        current_turn = get_current_turn(req.session_id)
        if req.turn_id < current_turn:
            logger.log(
                "tts_skipped_stale_turn", req.session_id, str(req.turn_id),
                detail={"current_turn": current_turn},
            )
            turn_key = f"{req.session_id}:{req.turn_id}"
            if turn_key in self._ws_sessions:
                from services.orchestrator.tts_client import close_ws_context
                ws, _ = self._ws_sessions.pop(turn_key)
                close_ws_context(ws, req.session_id, str(req.turn_id))
            return

        try:
            logger.log(
                "tts_request_received", req.session_id, str(req.turn_id),
                detail={
                    "text": req.text[:60],
                    "is_final_sentence": req.is_final_sentence,
                },
            )
            settings = get_settings()
            api_key = settings.cartesia_api_key
            mock = (
                not api_key
                or api_key == "dummy_val"
                or settings.env == "test"
            )
            logger.log(
                "tts_starting", req.session_id, str(req.turn_id),
                detail={"mock": mock},
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                self.executor, self._tts_sync, api_key, req, mock, loop
            )
        except Exception as e:
            logger.log_error(
                "tts_worker_processing_failed", req.session_id, str(req.turn_id), e
            )
            telemetry_bus.push(
                "error",
                {"message": f"TTS Stage Error: {e}"},
                req.session_id,
                str(req.turn_id),
            )
            # Always cap turn to prevent client hanging
            await self.output.put(
                AudioChunk(b"", req.session_id, req.turn_id, True)
            )

    def _tts_sync(
        self,
        api_key: str,
        req: TTSRequest,
        mock: bool,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        from services.orchestrator.tts_client import (
            _ws_continuation_supported,
            open_ws_context,
            speak_sentence_ws,
            close_ws_context,
            speak_stream_ws,
        )
        start_time = time.time()
        turn_key = f"{req.session_id}:{req.turn_id}"
        loop.call_soon_threadsafe(
            telemetry_bus.push,
            "tts_start",
            {"sentence_idx": 0, "is_final": req.is_final_sentence},
            req.session_id,
            str(req.turn_id),
        )

        def chunk_callback(chunk_data: bytes) -> None:
            if get_cancel_token(req.session_id).is_cancelled:
                return
            if get_current_turn(req.session_id) != req.turn_id:
                return
            loop.call_soon_threadsafe(
                telemetry_bus.push,
                "tts_chunk",
                {"sentence": req.text[:40]},
                req.session_id,
                str(req.turn_id),
            )
            asyncio.run_coroutine_threadsafe(
                self.output.put(
                    AudioChunk(chunk_data, req.session_id, req.turn_id, False)
                ),
                loop,
            )

        use_fallback = mock or (_ws_continuation_supported is False)
        if use_fallback:
            try:
                speak_stream_ws(
                    req.session_id, str(req.turn_id), req.text, chunk_callback
                )
                tok = get_cancel_token(req.session_id)
                if req.is_final_sentence and not tok.is_cancelled:
                    asyncio.run_coroutine_threadsafe(
                        self.output.put(
                            AudioChunk(b"", req.session_id, req.turn_id, True)
                        ),
                        loop,
                    )
                    latency_ms = int((time.time() - start_time) * 1000)
                    loop.call_soon_threadsafe(
                        telemetry_bus.push,
                        "tts_complete",
                        {"latency_ms": latency_ms},
                        req.session_id,
                        str(req.turn_id),
                    )
            except Exception as e:
                logger.log_error(
                    "tts_sync_error", req.session_id, str(req.turn_id), e
                )
                get_cancel_token(req.session_id).cancel("tts_synthesis_error")
                asyncio.run_coroutine_threadsafe(
                    self.output.put(
                        AudioChunk(b"", req.session_id, req.turn_id, True)
                    ),
                    loop,
                )
            return

        # --- Real Cartesia path: shared WS context per turn ---
        failed = False
        try:
            if turn_key not in self._ws_sessions:
                try:
                    ws, ctx = open_ws_context(req.session_id, str(req.turn_id))
                    self._ws_sessions[turn_key] = (ws, ctx)
                except Exception as conn_err:
                    logger.log_error(
                        "tts_ws_open_failed", req.session_id, str(req.turn_id),
                        conn_err,
                    )
                    speak_stream_ws(
                        req.session_id, str(req.turn_id), req.text, chunk_callback
                    )
                    tok = get_cancel_token(req.session_id)
                    if req.is_final_sentence and not tok.is_cancelled:
                        asyncio.run_coroutine_threadsafe(
                            self.output.put(
                                AudioChunk(b"", req.session_id, req.turn_id, True)
                            ),
                            loop,
                        )
                    return

            _, ctx = self._ws_sessions[turn_key]

            try:
                speak_sentence_ws(
                    req.session_id,
                    str(req.turn_id),
                    req.text,
                    chunk_callback,
                    ctx,
                    continue_=not req.is_final_sentence,
                )
            except (TypeError, AttributeError):
                import services.orchestrator.tts_client as _tc
                _tc._ws_continuation_supported = False
                failed = True
                raise

            tok = get_cancel_token(req.session_id)
            if req.is_final_sentence and not tok.is_cancelled:
                asyncio.run_coroutine_threadsafe(
                    self.output.put(
                        AudioChunk(b"", req.session_id, req.turn_id, True)
                    ),
                    loop,
                )
                latency_ms = int((time.time() - start_time) * 1000)
                loop.call_soon_threadsafe(
                    telemetry_bus.push,
                    "tts_complete",
                    {"latency_ms": latency_ms},
                    req.session_id,
                    str(req.turn_id),
                )

        except Exception as e:
            failed = True
            logger.log_error(
                "tts_sync_error", req.session_id, str(req.turn_id), e
            )
            get_cancel_token(req.session_id).cancel("tts_synthesis_error")
            asyncio.run_coroutine_threadsafe(
                self.output.put(
                    AudioChunk(b"", req.session_id, req.turn_id, True)
                ),
                loop,
            )

        finally:
            tok = get_cancel_token(req.session_id)
            should_close = req.is_final_sentence or tok.is_cancelled or failed
            if should_close and turn_key in self._ws_sessions:
                ws, _ = self._ws_sessions.pop(turn_key)
                close_ws_context(ws, req.session_id, str(req.turn_id))
