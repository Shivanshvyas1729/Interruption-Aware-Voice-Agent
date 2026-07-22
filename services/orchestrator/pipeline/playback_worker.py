"""
pipeline/playback_worker.py — Audio delivery stage.

Receives AudioChunk (and TextResponse) items, and delivers them to per-session
WebSocket client queues. One dedicated delivery task per session eliminates
head-of-line blocking between sessions.

Key design decisions:
  • Global distributor loop (run()) reads from self.input and dispatches
    instantly to per-session internal queues — O(1) per chunk.
  • _process_session() runs one coroutine per session: blocks on that
    client's slow send without affecting any other session.
  • Stale-turn and cancellation checks are performed inside the session loop
    so audio from a cancelled turn is never written to the wire.
  • AudioChunk(data=b"", is_last=True) acts as a terminal sentinel: on
    receipt the session loop emits playback_end, turn_complete telemetry and
    signals FSMWorker via PlaybackDoneMessage.

Telemetry emitted (consistent across all paths):
  • playback_start       — first audio byte delivered to client
  • playback_end         — last sentinel received (normal + cancelled paths)
  • turn_complete        — total wall-clock latency (normal path only)
  • playback_skipped_cancelled  — chunk dropped due to cancel flag
  • playback_skipped_stale_turn — chunk dropped (older turn_id)
  • error                       — unexpected exception
"""

import asyncio
import struct
import time
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from .base import PipelineStage
from .messages import AudioChunk, TextResponse, PlaybackDoneMessage
from .cancel_token import get_cancel_token, get_current_turn, cleanup_session

logger = get_logger("async-pipeline")


class PlaybackWorker(PipelineStage):
    def __init__(self):
        super().__init__("playback")
        self.input: asyncio.Queue = asyncio.Queue()
        self._clients: dict[str, asyncio.Queue] = {}
        self._playback_started: dict[str, float] = {}
        self._spoken_duration: dict[str, float] = {}
        self._session_queues: dict[str, asyncio.Queue] = {}
        self._session_tasks: dict[str, asyncio.Task] = {}
        self._dying_tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ #
    # Client registration                                                  #
    # ------------------------------------------------------------------ #

    def register_client(self, session_id: str, queue: asyncio.Queue):
        self._clients[session_id] = queue
        if session_id not in self._spoken_duration:
            self._spoken_duration[session_id] = 0.0
        if session_id not in self._session_queues:
            self._session_queues[session_id] = asyncio.Queue()
        task = self._session_tasks.get(session_id)
        if not task or task.done():
            self._session_tasks[session_id] = asyncio.create_task(
                self._process_session(session_id),
                name=f"playback-session-{session_id}",
            )

    def unregister_client(self, session_id: str):
        self._clients.pop(session_id, None)
        self._spoken_duration.pop(session_id, None)
        self._playback_started.pop(session_id, None)
        self._session_queues.pop(session_id, None)
        task = self._session_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            self._dying_tasks.add(task)
            task.add_done_callback(self._dying_tasks.discard)
        cleanup_session(session_id)

    async def stop(self):
        await super().stop()
        for task in list(self._session_tasks.values()):
            if not task.done():
                task.cancel()
        if self._session_tasks:
            await asyncio.gather(*self._session_tasks.values(), return_exceptions=True)
        self._session_tasks.clear()
        if self._dying_tasks:
            await asyncio.gather(*self._dying_tasks, return_exceptions=True)
        self._dying_tasks.clear()
        self._session_queues.clear()

    # ------------------------------------------------------------------ #
    # Metrics helpers                                                       #
    # ------------------------------------------------------------------ #

    def get_spoken_duration(self, session_id: str) -> float:
        return self._spoken_duration.get(session_id, 0.0)

    def reset_spoken_duration(self, session_id: str):
        self._spoken_duration[session_id] = 0.0

    # ------------------------------------------------------------------ #
    # Global distributor loop                                              #
    # ------------------------------------------------------------------ #

    async def run(self):
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

    # ------------------------------------------------------------------ #
    # Per-session delivery coroutine                                        #
    # ------------------------------------------------------------------ #

    async def _process_session(self, session_id: str):
        q_internal = self._session_queues.get(session_id)
        if not q_internal:
            return

        try:
            while not self._cancel_event.is_set():
                try:
                    chunk = await q_internal.get()
                except asyncio.CancelledError:
                    break

                try:
                    tok = get_cancel_token(chunk.session_id)
                    if tok.is_cancelled:
                        logger.log(
                            "playback_skipped_cancelled",
                            chunk.session_id, str(chunk.turn_id), detail={},
                        )
                        self._playback_started.pop(chunk.session_id, None)
                        continue

                    if isinstance(chunk, AudioChunk):
                        current_turn = get_current_turn(chunk.session_id)
                        if chunk.turn_id < current_turn:
                            logger.log(
                                "playback_skipped_stale_turn",
                                chunk.session_id, str(chunk.turn_id),
                                detail={"current_turn": current_turn},
                            )
                            self._playback_started.pop(chunk.session_id, None)
                            continue

                    q_client = self._clients.get(chunk.session_id)
                    if q_client:
                        if isinstance(chunk, AudioChunk) and chunk.data:
                            if chunk.session_id not in self._playback_started:
                                self._playback_started[chunk.session_id] = time.time()
                            telemetry_bus.push(
                                "playback_start", {},
                                chunk.session_id, str(chunk.turn_id),
                            )
                        # Accumulate spoken duration (PCM 16-bit mono 48 kHz)
                        chunk_duration = len(chunk.data) / 48000.0
                        self._spoken_duration[chunk.session_id] = (
                            self._spoken_duration.get(chunk.session_id, 0.0)
                            + chunk_duration
                        )
                        tagged = struct.pack("<I", chunk.turn_id) + chunk.data
                        await q_client.put(tagged)

                    elif isinstance(chunk, AudioChunk) and chunk.is_last:
                        await q_client.put(struct.pack("<I", chunk.turn_id))

                    elif isinstance(chunk, TextResponse):
                        await q_client.put(
                            {
                                "type": "llm_response",
                                "text": chunk.text,
                                "turn_id": chunk.turn_id,
                                "tokens": chunk.tokens,
                                "latency_ms": chunk.latency_ms,
                                "pause_duration_ms": getattr(chunk, "pause_duration_ms", 0),
                            }
                        )

                    # Emit playback_end + turn_complete on sentinel
                    if isinstance(chunk, AudioChunk) and chunk.is_last:
                        start_time = self._playback_started.pop(chunk.session_id, None)
                        telemetry_bus.push(
                            "playback_end", {},
                            chunk.session_id, str(chunk.turn_id),
                        )
                        if start_time:
                            total_latency_ms = int((time.time() - start_time) * 1000)
                            telemetry_bus.push(
                                "turn_complete",
                                {"total_latency_ms": total_latency_ms},
                                chunk.session_id, str(chunk.turn_id),
                            )

                        # Notify FSMWorker that playback is done
                        from .voice_pipeline import get_pipeline
                        pipeline = get_pipeline()
                        if (
                            pipeline
                            and pipeline.fsm
                            and hasattr(pipeline.fsm, "playback_done_input")
                            and pipeline.fsm.playback_done_input
                        ):
                            pipeline.fsm.playback_done_input.put_nowait(
                                PlaybackDoneMessage(
                                    session_id=chunk.session_id,
                                    turn_id=chunk.turn_id,
                                )
                            )

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.log_error(
                        "playback_worker_session_error",
                        chunk.session_id, str(chunk.turn_id), e,
                    )
                    telemetry_bus.push(
                        "error",
                        {"message": f"Playback Stage Session Error: {e}"},
                        chunk.session_id, str(chunk.turn_id),
                    )
                finally:
                    q_internal.task_done()
        finally:
            self._playback_started.pop(session_id, None)
            self._spoken_duration.pop(session_id, None)
