"""
pipeline/stt_worker.py — Speech-to-Text stage.

In the current architecture the browser sends final transcripts as text via
WebSocket (using the Web Speech API). This worker is a thin pass-through that
stamps telemetry and forwards to FSMWorker. A future raw-audio mode would call
Deepgram / Whisper here instead.

Telemetry emitted:
  • stt_final   — transcript received and forwarded (all paths)
  • error        — only on unexpected exception
"""

import asyncio
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from .base import PipelineStage
from .messages import TranscriptMessage

logger = get_logger("async-pipeline")


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
                # Emit consistent stt_final telemetry on every path.
                telemetry_bus.push(
                    "stt_final",
                    {"text": msg.text[:80]},
                    msg.session_id,
                    str(msg.turn_id),
                )
                await self.output.put(
                    TranscriptMessage(
                        text=msg.text,
                        session_id=msg.session_id,
                        turn_id=msg.turn_id,
                        is_final=True,
                    )
                )
            except Exception as e:
                sid = getattr(msg, "session_id", "system")
                logger.log_error("stt_worker_error", sid, "system", e)
                telemetry_bus.push(
                    "error",
                    {"message": f"STT Stage Error: {e}"},
                    sid,
                    "system",
                )
