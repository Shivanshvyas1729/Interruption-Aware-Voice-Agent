"""
pipeline/messages.py — all inter-worker message dataclasses.

Workers communicate exclusively through these typed messages via asyncio.Queue.
No business logic here — pure data containers.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TranscriptMessage:
    """Final STT transcript coming from browser / STT Worker."""
    text: str
    session_id: str
    turn_id: int
    is_final: bool = True
    stt_latency_ms: int = 0


@dataclass
class LLMRequest:
    """Request sent from FSMWorker → LLMWorker."""
    messages: list[dict]
    session_id: str
    turn_id: int
    max_tokens: int | None = None
    max_sentences: int | None = None


@dataclass
class LLMResponse:
    """Legacy single-shot LLM response (kept for test injection paths)."""
    text: str
    session_id: str
    turn_id: int
    tokens: int = 0
    latency_ms: int = 0


@dataclass
class TextResponse:
    """Full reply text forwarded to Playback for UI display."""
    text: str
    session_id: str
    turn_id: int
    tokens: int = 0
    latency_ms: int = 0


@dataclass
class LLMSentenceChunk:
    """One sentence emitted by LLMWorker; is_final marks the last sentence of a turn."""
    text: str
    session_id: str
    turn_id: int
    sentence_index: int
    is_final: bool = False
    # Populated only on is_final=True — carries full accumulated reply.
    full_reply_text: str = ""
    tokens: int = 0
    latency_ms: int = 0


@dataclass
class TTSRequest:
    """One sentence sent from FSMWorker → TTSWorker for synthesis."""
    text: str
    session_id: str
    turn_id: int
    is_final_sentence: bool = False  # gates AudioChunk(is_last=True) in TTSWorker


@dataclass
class AudioChunk:
    """PCM audio bytes streamed from TTSWorker → PlaybackWorker."""
    data: bytes
    session_id: str
    turn_id: int
    is_last: bool = False


@dataclass
class InterruptEvent:
    """VAD / barge-in / stop-button signal from browser → InterruptMonitorWorker."""
    session_id: str
    kind: str  # "vad_start" | "barge_in" | "stop_button"
    detail: dict = field(default_factory=dict)


@dataclass
class CancelCommand:
    """Cancellation instruction routed through FSMWorker."""
    session_id: str
    reason: str


@dataclass
class MetricsEvent:
    """Generic telemetry event pushed to MetricsWorker."""
    event_type: str
    session_id: str
    turn_id: str
    data: dict = field(default_factory=dict)


@dataclass
class FSMTransition:
    """State-machine transition notification (informational, not yet consumed)."""
    session_id: str
    turn_id: int
    new_state: str
    data: dict = field(default_factory=dict)


@dataclass
class WordMessage:
    """Individual spoken word tracked for interruption context."""
    session_id: str
    word: str


@dataclass
class PlaybackDoneMessage:
    """Signal emitted when PlaybackWorker finishes the last audio chunk for a turn."""
    session_id: str
    turn_id: int
