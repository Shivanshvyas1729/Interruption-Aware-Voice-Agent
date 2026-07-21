"""
async_pipeline.py — backward-compatibility shim.

The pipeline was refactored into services/orchestrator/pipeline/ sub-modules.
This file re-exports every public symbol so that existing import statements
(api_gateway.py, tts_client.py, llm_client.py, etc.) continue to work without
any changes.

DO NOT add new logic here. Edit the appropriate sub-module instead:
  pipeline/messages.py        — message dataclasses
  pipeline/cancel_token.py    — CancelToken, get/set/reset helpers
  pipeline/base.py            — PipelineStage ABC
  pipeline/stt_worker.py      — STTWorker
  pipeline/llm_worker.py      — LLMWorker
  pipeline/tts_worker.py      — TTSWorker
  pipeline/playback_worker.py — PlaybackWorker
  pipeline/fsm_worker.py      — FSMWorker
  pipeline/interrupt_worker.py— InterruptMonitorWorker
  pipeline/metrics_worker.py  — MetricsWorker
  pipeline/voice_pipeline.py  — VoicePipeline, get_pipeline, shutdown_pipeline
"""

from services.orchestrator.pipeline import (
    # Messages
    TranscriptMessage, LLMRequest, LLMResponse, TextResponse,
    LLMSentenceChunk, TTSRequest, AudioChunk, InterruptEvent,
    CancelCommand, MetricsEvent, FSMTransition, WordMessage,
    PlaybackDoneMessage,

    # Cancellation
    CancelToken, get_cancel_token, reset_cancel_token,
    cleanup_session, get_current_turn, set_current_turn,

    # Base
    PipelineError, PipelineStage,

    # Workers
    STTWorker, LLMWorker, TTSWorker, PlaybackWorker,
    FSMWorker, InterruptMonitorWorker, MetricsWorker,

    # Orchestrator
    VoicePipeline, get_pipeline, shutdown_pipeline,
)

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
