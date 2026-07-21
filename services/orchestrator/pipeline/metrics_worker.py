"""
pipeline/metrics_worker.py — Metrics / telemetry bus bridge.

Consumes MetricsEvent items from FSMWorker and forwards them to the global
TelemetryBus singleton. This decouples FSMWorker from the telemetry bus and
allows MetricsEvents to be batched or filtered in the future without changing
FSMWorker.
"""

import asyncio
from common.logging.logger import get_logger
from services.edge_auth.telemetry_bus import telemetry_bus
from .base import PipelineStage

logger = get_logger("async-pipeline")


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
                telemetry_bus.push(
                    ev.event_type, ev.data, ev.session_id, ev.turn_id
                )
            except Exception as e:
                logger.log_error(
                    "metrics_worker_error",
                    getattr(ev, "session_id", "system"), "system", e,
                )
