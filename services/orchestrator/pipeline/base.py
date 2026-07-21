"""
pipeline/base.py — abstract base class for all pipeline stage workers.

Every worker (STT, LLM, TTS, Playback, FSM, Interrupt, Metrics) inherits
PipelineStage. The base class handles start/stop lifecycle and wraps run()
with structured error logging so stages never silently die.
"""

import asyncio
import traceback
from abc import ABC, abstractmethod
from common.logging.logger import get_logger

logger = get_logger("async-pipeline")


class PipelineError(Exception):
    """Raised for unrecoverable pipeline configuration errors."""
    pass


class PipelineStage(ABC):
    """
    Base class for every async pipeline worker.

    Lifecycle:
        stage.start()   → spawns asyncio.Task running _run_wrapper → run()
        stage.stop()    → sets cancel event, cancels task, awaits cleanup
    """

    def __init__(self, name: str):
        self.name = name
        self._task: asyncio.Task | None = None
        self._cancel_event = asyncio.Event()

    @abstractmethod
    async def run(self):
        """Override with the stage's main loop. Must honour self._cancel_event."""
        ...

    def start(self):
        if self._task is None or self._task.done():
            self._cancel_event.clear()
            self._task = asyncio.create_task(
                self._run_wrapper(), name=self.name
            )
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
            logger.log(
                "pipeline_stage_cancelled", "system", "system",
                detail={"stage": self.name},
            )
        except Exception as e:
            logger.log_error(
                "pipeline_stage_error", "system", "system", e, stage=self.name
            )
            traceback.print_exc()
