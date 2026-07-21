"""
pipeline/llm_worker.py — LLM generation stage.

Accepts LLMRequest items, calls the primary streaming LLM, and emits
LLMSentenceChunk items to its output queue (consumed by FSMWorker).

Key design decisions:
  • Lookahead-1 sentence buffer: dispatches sentence[N-1] as is_final=False
    when sentence[N] arrives, then dispatches the last one as is_final=True.
    This allows TTS to start on sentence 1 before the LLM finishes, reducing
    perceptible latency.
  • Per-session task chaining preserves turn ordering within a session while
    allowing different sessions to generate concurrently on the thread pool.
  • A terminal is_final=True chunk is always emitted even on error, so the
    FSMWorker's pending-response store and PlaybackDone signal always fire.

Telemetry emitted (consistent across all paths):
  • llm_request_received    — when request is picked up from queue
  • llm_first_token         — emitted by llm_client.call_primary_streaming
  • llm_complete            — emitted by llm_client.call_primary_streaming
  • llm_turn_dispatched     — after all sentences are queued
  • llm_cancelled_post_executor — if cancelled after executor returns
  • error                   — on unexpected exception (all error paths)
"""

import asyncio
import time
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from .base import PipelineStage
from .messages import LLMRequest, LLMSentenceChunk
from .cancel_token import get_cancel_token

logger = get_logger("async-pipeline")


class LLMWorker(PipelineStage):
    def __init__(self):
        super().__init__("llm")
        self.input: asyncio.Queue = asyncio.Queue()
        self.output: asyncio.Queue = asyncio.Queue()
        self._session_tasks: dict[str, asyncio.Task] = {}
        self.executor = None

    def start(self):
        from concurrent.futures import ThreadPoolExecutor
        from common.config import voice_settings
        max_workers = voice_settings.get("concurrency.llm_max_workers", 100)
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="llm_worker"
        )
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

            prev_task = self._session_tasks.get(req.session_id)
            task = asyncio.create_task(
                self._process_request(req, prev_task),
                name=f"llm-{req.session_id}-{req.turn_id}",
            )
            self._session_tasks[req.session_id] = task

            def _on_done(t, sid=req.session_id):
                if self._session_tasks.get(sid) is t:
                    self._session_tasks.pop(sid, None)
            task.add_done_callback(_on_done)

    async def _process_request(
        self, req: LLMRequest, prev_task: "asyncio.Task | None"
    ):
        if prev_task is not None:
            if not prev_task.done():
                try:
                    await prev_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.log_error(
                        "llm_prior_task_failed", req.session_id, str(req.turn_id), e
                    )
            else:
                if not prev_task.cancelled():
                    try:
                        exc = prev_task.exception()
                        if exc is not None:
                            logger.log_error(
                                "llm_prior_task_failed",
                                req.session_id, str(req.turn_id), exc,
                            )
                    except Exception:
                        pass

        tok = get_cancel_token(req.session_id)
        if tok.is_cancelled:
            return

        logger.log(
            "llm_request_received", req.session_id, str(req.turn_id),
            detail={"messages": len(req.messages)},
        )

        loop = asyncio.get_event_loop()
        t0 = time.time()
        try:
            from services.orchestrator.llm_client import call_primary_streaming
            from services.orchestrator.failover import primary_circuit_breaker
            from services.orchestrator.context_manager import estimate_tokens
            from common.config.voice_settings import get as vc_get

            pending: list = [None]
            sentence_index: list = [0]
            output_q = self.output
            max_sentences = (
                req.max_sentences
                if req.max_sentences is not None
                else vc_get("llm.max_sentences", 3)
            )

            def _sentence_callback(sentence_text: str) -> None:
                idx = sentence_index[0]
                if idx >= max_sentences:
                    return
                sentence_index[0] += 1
                if pending[0] is not None:
                    prev_idx, prev_text = pending[0]
                    if not tok.is_cancelled:
                        asyncio.run_coroutine_threadsafe(
                            output_q.put(
                                LLMSentenceChunk(
                                    text=prev_text,
                                    session_id=req.session_id,
                                    turn_id=req.turn_id,
                                    sentence_index=prev_idx,
                                    is_final=False,
                                )
                            ),
                            loop,
                        )
                pending[0] = (idx, sentence_text)

            def _llm_streaming_task() -> str:
                try:
                    system_prompt = None
                    if req.max_sentences and req.max_sentences > 3:
                        system_prompt = (
                            "You are a low-latency real-time voice assistant. "
                            "Provide a detailed, descriptive response addressing "
                            "the query in depth. Keep sentences short, clear, and "
                            "informative. Each sentence must be a self-contained, "
                            "speakable chunk. Put the most important facts first, "
                            "and avoid listing points or using formatting."
                        )
                    full_text = call_primary_streaming(
                        req.session_id,
                        str(req.turn_id),
                        req.messages,
                        _sentence_callback,
                        max_tokens=req.max_tokens,
                        system_prompt=system_prompt,
                    )
                except Exception:
                    if not tok.is_cancelled:
                        asyncio.run_coroutine_threadsafe(
                            output_q.put(
                                LLMSentenceChunk(
                                    text="I'm sorry, I encountered an error.",
                                    session_id=req.session_id,
                                    turn_id=req.turn_id,
                                    sentence_index=sentence_index[0],
                                    is_final=True,
                                    full_reply_text="I'm sorry, I encountered an error.",
                                    tokens=0,
                                    latency_ms=int((time.time() - t0) * 1000),
                                )
                            ),
                            loop,
                        ).result()
                    raise

                if not tok.is_cancelled:
                    tokens = estimate_tokens(full_text)
                    if pending[0] is not None:
                        final_idx, final_text = pending[0]
                    else:
                        final_idx, final_text = 0, full_text
                    asyncio.run_coroutine_threadsafe(
                        output_q.put(
                            LLMSentenceChunk(
                                text=final_text,
                                session_id=req.session_id,
                                turn_id=req.turn_id,
                                sentence_index=final_idx,
                                is_final=True,
                                full_reply_text=full_text,
                                tokens=tokens,
                                latency_ms=int((time.time() - t0) * 1000),
                            )
                        ),
                        loop,
                    ).result()

                return full_text

            await loop.run_in_executor(self.executor, _llm_streaming_task)

            if tok.is_cancelled:
                logger.log(
                    "llm_cancelled_post_executor",
                    req.session_id, str(req.turn_id), detail={},
                )
                return

            provider = "openai" if primary_circuit_breaker.is_open() else "groq"
            logger.log(
                "llm_turn_dispatched", req.session_id, str(req.turn_id),
                detail={"provider": provider, "sentences": sentence_index[0]},
            )

        except Exception as outer_err:
            logger.log_error(
                "llm_worker_processing_failed",
                req.session_id, str(req.turn_id), outer_err,
            )
            telemetry_bus.push(
                "error",
                {"message": f"LLM Stage Error: {outer_err}"},
                req.session_id,
                str(req.turn_id),
            )
