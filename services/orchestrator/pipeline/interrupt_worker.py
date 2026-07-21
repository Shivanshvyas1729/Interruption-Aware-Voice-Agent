"""
pipeline/interrupt_worker.py — Interrupt Monitor stage.

Listens for VAD / barge-in / stop-button events from the browser, applies
the dual-write cancellation (CancelToken + CancellationManager), emits a
vad_start telemetry event, and forwards a CancelCommand to FSMWorker.

Telemetry emitted (all interrupt kinds):
  • vad_start   — on vad_start or barge_in (before CancelCommand is queued)
  • error        — on unexpected exception
"""

import asyncio
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from .base import PipelineStage
from .messages import CancelCommand
from .cancel_token import get_cancel_token

logger = get_logger("async-pipeline")


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
                        # DUAL-WRITE CANCEL: update both CancelToken and
                        # CancellationManager so streaming executor threads
                        # that check either mechanism see the flag.
                        tok.cancel(event.kind)
                        from services.orchestrator.cancellation_manager import (
                            cancellation_manager,
                        )
                        cancellation_manager.cancel_session(
                            event.session_id, event.kind
                        )
                        telemetry_bus.push(
                            "vad_start", {}, event.session_id, "system"
                        )
                        await self.output.put(
                            CancelCommand(event.session_id, event.kind)
                        )

                elif event.kind == "stop_button":
                    tok = get_cancel_token(event.session_id)
                    tok.cancel("stop_button")
                    from services.orchestrator.cancellation_manager import (
                        cancellation_manager,
                    )
                    cancellation_manager.cancel_session(
                        event.session_id, "stop_button"
                    )
                    await self.output.put(
                        CancelCommand(event.session_id, "stop_button")
                    )

            except Exception as e:
                sid = getattr(event, "session_id", "system")
                logger.log_error("interrupt_monitor_worker_error", sid, "system", e)
                telemetry_bus.push(
                    "error",
                    {"message": f"Interrupt Monitor Error: {e}"},
                    sid, "system",
                )
