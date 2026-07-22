"""
pipeline/tts_worker.py — Text-to-Speech synthesis stage.

Accepts TTSRequest items (one per sentence), synthesises audio via Cartesia,
and emits AudioChunk items to the Playback worker.

Delegates all socket lifecycle, pre-warming, context creation, and connection pooling
to the dedicated TTSConnectionManager.
"""

import asyncio
import time
from common.config.settings import get_settings
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from services.orchestrator.tts_connection_manager import get_connection_manager
from .base import PipelineStage
from .messages import TTSRequest, AudioChunk
from .cancel_token import get_cancel_token, get_current_turn

logger = get_logger("async-pipeline")


class TTSWorker(PipelineStage):
    def __init__(self):
        super().__init__("tts")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()
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
        get_connection_manager().start()

    async def stop(self):
        await super().stop()
        if self.executor:
            self.executor.shutdown(wait=False)
        get_connection_manager().shutdown()

    def cleanup_session_ws(self, session_id: str) -> None:
        get_connection_manager().cleanup(session_id)

    async def prewarm_session(self, session_id: str) -> None:
        if not self.executor:
            return
        loop = asyncio.get_running_loop()
        conn_mgr = get_connection_manager()
        await loop.run_in_executor(self.executor, conn_mgr.prewarm, session_id, self.executor)

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
        conn_mgr = get_connection_manager()
        tok = get_cancel_token(req.session_id)
        if tok.is_cancelled:
            return

        if prev_task is not None and not prev_task.done():
            prev_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(prev_task), timeout=0.05)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass
            # Force-drop the stale WS context so the new turn always gets a fresh
            # connection — this prevents concurrent recv() across turns (ConcurrencyError).
            conn_mgr.release(req.session_id, cancelled=True)

        tok = get_cancel_token(req.session_id)
        if tok.is_cancelled:
            logger.log(
                "tts_skipped_cancelled_post_wait",
                req.session_id, str(req.turn_id), detail={},
            )
            return

        current_turn = get_current_turn(req.session_id)
        if req.turn_id < current_turn:
            logger.log(
                "tts_skipped_stale_turn", req.session_id, str(req.turn_id),
                detail={"current_turn": current_turn},
            )
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
            speak_sentence_ws,
            speak_stream_ws,
        )
        start_time = time.time()
        conn_mgr = get_connection_manager()
        loop.call_soon_threadsafe(
            telemetry_bus.push,
            "tts_start",
            {"sentence_idx": 0, "is_final": req.is_final_sentence},
            req.session_id,
            str(req.turn_id),
        )

        first_chunk_fired = [False]

        def chunk_callback(chunk_data: bytes) -> None:
            if get_cancel_token(req.session_id).is_cancelled:
                return
            if get_current_turn(req.session_id) != req.turn_id:
                return
            if not first_chunk_fired[0]:
                first_chunk_fired[0] = True
                latency_ms = int((time.time() - start_time) * 1000)
                loop.call_soon_threadsafe(
                    telemetry_bus.push,
                    "tts_first_audio",
                    {"latency_ms": latency_ms},
                    req.session_id,
                    str(req.turn_id),
                )
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

        use_fallback = mock or conn_mgr.is_continuation_failed(req.session_id)
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

        # --- Real Cartesia path: persistent WS connection via Connection Manager ---
        failed = False
        try:
            try:
                ws, ctx = conn_mgr.acquire(req.session_id, str(req.turn_id))
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
                conn_mgr.mark_continuation_failed(req.session_id)
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
            conn_mgr.release(
                req.session_id, failed=failed, cancelled=tok.is_cancelled
            )
