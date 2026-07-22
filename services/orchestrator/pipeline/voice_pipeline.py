"""
pipeline/voice_pipeline.py — Top-level orchestrator and global singleton.

VoicePipeline creates, wires, starts, and stops all pipeline workers.
It exposes a minimal public API used by api_gateway.py and edge_auth.
"""

import asyncio
from common.logging.logger import get_logger
from .stt_worker import STTWorker
from .llm_worker import LLMWorker
from .tts_worker import TTSWorker
from .playback_worker import PlaybackWorker
from .fsm_worker import FSMWorker
from .interrupt_worker import InterruptMonitorWorker
from .metrics_worker import MetricsWorker
from .messages import TranscriptMessage, InterruptEvent, CancelCommand

logger = get_logger("async-pipeline")

_main_loop = None
_pipeline: "VoicePipeline | None" = None


class VoicePipeline:
    """Top-level orchestrator: creates, connects, and manages all workers."""

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

        global _main_loop
        _main_loop = asyncio.get_running_loop()

        # Re-create queues inside the running loop so they are bound to the
        # correct event loop (important for thread-safe run_coroutine_threadsafe).
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

        # Wire queues between stages
        self.stt.output          = self.fsm.transcript_input   # STT → FSM
        self.fsm.llm_input       = self.llm.input               # FSM → LLM
        self.llm.output          = self.fsm.llm_output          # LLM → FSM
        self.fsm.tts_input       = self.tts.input               # FSM → TTS
        self.tts.output          = self.playback.input          # TTS → Playback
        self.interrupt.output    = self.fsm.cancel_input        # Interrupt → FSM
        self.fsm.metrics_output  = self.metrics.input           # FSM → Metrics
        self.fsm.playback_input  = self.playback.input          # FSM → Playback (text)
        self.fsm.playback        = self.playback                # back-reference

        for stage in [
            self.stt, self.llm, self.tts, self.playback,
            self.fsm, self.interrupt, self.metrics,
        ]:
            stage.start()

        self._started = True

    async def stop(self):
        logger.log_service_stop("voice-pipeline", detail={"reason": "shutdown"})
        for stage in [
            self.stt, self.llm, self.tts, self.playback,
            self.fsm, self.interrupt, self.metrics,
        ]:
            await stage.stop()
        self._started = False

    # ------------------------------------------------------------------ #
    # Public submission API                                                #
    # ------------------------------------------------------------------ #

    async def submit_transcript(
        self, session_id: str, text: str, turn_id: int = 0
    ):
        await self.stt.input.put(
            TranscriptMessage(text=text, session_id=session_id, turn_id=turn_id)
        )

    async def submit_interrupt(self, session_id: str, kind: str):
        await self.interrupt.input.put(
            InterruptEvent(session_id=session_id, kind=kind)
        )

    async def submit_cancel(self, session_id: str, reason: str):
        await self.fsm.cancel_input.put(
            CancelCommand(session_id=session_id, reason=reason)
        )

    def cancel_inflight_tasks(self, session_id: str):
        """Preemptively cancel in-flight LLM and TTS asyncio.Tasks for a session.

        This is called from FSM._handle_cancel so that blocking executor calls
        (Groq streaming, Cartesia WS) are interrupted immediately rather than
        waiting for the next cooperative cancellation check.
        """
        llm_task = self.llm._session_tasks.get(session_id)
        if llm_task and not llm_task.done():
            llm_task.cancel()

        tts_task = self.tts._session_tasks.get(session_id)
        if tts_task and not tts_task.done():
            tts_task.cancel()

    # ------------------------------------------------------------------ #
    # Client registration / cleanup                                        #
    # ------------------------------------------------------------------ #

    def register_playback_client(self, session_id: str, queue: asyncio.Queue):
        self.playback.register_client(session_id, queue)

    async def prewarm_session(self, session_id: str):
        if hasattr(self, "tts"):
            await self.tts.prewarm_session(session_id)

    def unregister_playback_client(self, session_id: str):
        self.playback.unregister_client(session_id)

        llm_task = self.llm._session_tasks.pop(session_id, None)
        if llm_task and not llm_task.done():
            llm_task.cancel()

        tts_task = self.tts._session_tasks.pop(session_id, None)
        if tts_task and not tts_task.done():
            tts_task.cancel()

        if hasattr(self, "tts"):
            self.tts.cleanup_session_ws(session_id)

        self.fsm.cleanup_session(session_id)

    def register_task(self, session_id: str, task: asyncio.Task):
        # Kept for API compatibility; task tracking now done per-worker.
        pass


# ------------------------------------------------------------------ #
# Global singleton helpers                                             #
# ------------------------------------------------------------------ #

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
