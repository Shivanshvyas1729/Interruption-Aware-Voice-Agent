"""
services.orchestrator.pipeline — modular async voice pipeline.

Architecture:
  STTWorker → FSMWorker → LLMWorker → TTSWorker → PlaybackWorker
                  ↑               ↑
           InterruptMonitorWorker  CancellationManager
                  ↓               ↓
             MetricsWorker (telemetry bus)

Import from here directly or use the convenience shim in async_pipeline.py.
"""

from .messages import (
    TranscriptMessage, LLMRequest, LLMResponse, TextResponse,
    LLMSentenceChunk, TTSRequest, AudioChunk, InterruptEvent,
    CancelCommand, MetricsEvent, FSMTransition, WordMessage,
    PlaybackDoneMessage,
)
from .cancel_token import (
    CancelToken, get_cancel_token, reset_cancel_token,
    cleanup_session, get_current_turn, set_current_turn,
)
from .base import PipelineError, PipelineStage
from .stt_worker import STTWorker
from .llm_worker import LLMWorker
from .tts_worker import TTSWorker
from .playback_worker import PlaybackWorker
from .fsm_worker import FSMWorker
from .interrupt_worker import InterruptMonitorWorker
from .metrics_worker import MetricsWorker
from .voice_pipeline import VoicePipeline, get_pipeline, shutdown_pipeline

__all__ = [
    "TranscriptMessage", "LLMRequest", "LLMResponse", "TextResponse",
    "LLMSentenceChunk", "TTSRequest", "AudioChunk", "InterruptEvent",
    "CancelCommand", "MetricsEvent", "FSMTransition", "WordMessage",
    "PlaybackDoneMessage",
    "CancelToken", "get_cancel_token", "reset_cancel_token",
    "cleanup_session", "get_current_turn", "set_current_turn",
    "PipelineError", "PipelineStage",
    "STTWorker", "LLMWorker", "TTSWorker", "PlaybackWorker",
    "FSMWorker", "InterruptMonitorWorker", "MetricsWorker",
    "VoicePipeline", "get_pipeline", "shutdown_pipeline",
]
