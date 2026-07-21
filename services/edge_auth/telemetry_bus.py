import asyncio
import time
import json
from collections import deque

class TelemetryEvent:
    __slots__ = ("event_type", "data", "timestamp", "session_id", "turn_id")

    def __init__(self, event_type: str, data: dict = None, session_id: str = "", turn_id: str = ""):
        self.event_type = event_type
        self.data = data or {}
        self.timestamp = time.time()
        self.session_id = session_id
        self.turn_id = turn_id

    def to_dict(self):
        return {
            "type": self.event_type,
            "data": self.data,
            "ts": self.timestamp,
            "session_id": self.session_id,
            "turn_id": self.turn_id
        }


class TelemetryBus:
    """In-memory event bus that broadcasts telemetry events to all connected WebSocket listeners."""

    def __init__(self, max_history: int = None):
        from common.config.voice_settings import get as vc_get
        if max_history is None:
            max_history = vc_get("telemetry.max_history", 500)
        self._history: deque = deque(maxlen=max_history)
        self._listeners: set = set()
        self._session_metrics: dict = {}
        self._timeline_tracker = TurnTimelineTracker()

    def push(self, event_type: str, data: dict = None, session_id: str = "", turn_id: str = ""):
        # Prevent stale or duplicate turn telemetry under concurrency.
        # Import lazily and from the leaf module to avoid circular imports.
        if session_id and turn_id and str(turn_id).isdigit():
            try:
                from services.orchestrator.pipeline.cancel_token import get_current_turn
                current = get_current_turn(session_id)
                if int(turn_id) < current:
                    return  # Discard stale event from an older turn
            except Exception:
                pass

        event = TelemetryEvent(event_type, data, session_id, turn_id)
        self._history.append(event)

        # Track per-session metrics automatically
        self._update_session_metrics(event)

        # Update per-turn timeline tracking
        self._timeline_tracker.process_event(event)

        # Broadcast to all connected WS listeners
        if self._listeners:
            payload = json.dumps(event.to_dict())
            for ws in self._listeners.copy():
                try:
                    ws.put_nowait(payload)
                except Exception:
                    self._listeners.discard(ws)

    def _update_session_metrics(self, event: TelemetryEvent):
        sid = event.session_id or "_global"
        if sid not in self._session_metrics:
            self._session_metrics[sid] = {}
        self._session_metrics[sid][event.event_type] = {
            "ts": event.timestamp,
            "data": event.data
        }

    def register(self, ws: asyncio.Queue) -> list:
        """Register a WS listener queue and return history snapshot."""
        self._listeners.add(ws)
        return [e.to_dict() for e in self._history]

    def unregister(self, ws: asyncio.Queue):
        self._listeners.discard(ws)

    def get_latest(self, event_type: str, session_id: str = "") -> dict:
        if session_id and session_id in self._session_metrics:
            return self._session_metrics[session_id].get(event_type)
        # Search history in reverse
        for e in reversed(self._history):
            if e.event_type == event_type:
                return {"ts": e.timestamp, "data": e.data}
        return None

    def recent_events(self, limit: int = None) -> list:
        from common.config.voice_settings import get as vc_get
        if limit is None:
            limit = vc_get("telemetry.recent_events_limit", 50)
        return [e.to_dict() for e in list(self._history)[-limit:]]


class TurnTimelineTracker:
    def __init__(self):
        self._timelines = {}  # (session_id, turn_id) -> dict
        self._latest_vad_start = {}  # session_id -> float (timestamp)
        self._setup_logger()

    def _setup_logger(self):
        import logging
        from logging.handlers import RotatingFileHandler
        import os
        
        self.logger = logging.getLogger("turn_timeline")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        
        # Ensure log dir exists
        os.makedirs("logs", exist_ok=True)
        if not self.logger.handlers:
            handler = RotatingFileHandler(
                "logs/turn_timeline.log",
                maxBytes=10*1024*1024,
                backupCount=5,
                encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)

    def process_event(self, event):
        etype = event.event_type
        sid = event.session_id
        tid = event.turn_id
        ts = event.timestamp
        data = event.data or {}

        if not sid or sid == "system":
            return

        # Track VAD Start at session level
        if etype == "vad_start":
            self._latest_vad_start[sid] = ts
            return

        # If a session-level cancellation comes in, flush any active turn
        if etype == "cancellation":
            self.flush_session(sid, reason="cancellation")
            return

        # Enforce that only valid numeric turn IDs are aggregated
        is_valid_turn = tid and str(tid).isdigit()
        if not is_valid_turn:
            return

        # STT final or LLM request triggers a new turn timeline
        if etype in ("stt_final", "llm_request"):
            # Flush any previous turns for this session to make sure they are written
            self._flush_previous_turns(sid, tid)
            if (sid, tid) not in self._timelines:
                self._timelines[(sid, tid)] = {
                    "session_id": sid,
                    "turn_id": int(tid) if str(tid).isdigit() else tid,
                    "vad_triggered_at": self._latest_vad_start.get(sid),
                        "stt_start": self._latest_vad_start.get(sid),
                        "stt_end": None,
                        "llm_request_sent": None,
                        "llm_first_token": None,
                        "llm_complete": None,
                        "tts_request_sent": None,
                        "tts_first_chunk": None,
                        "tts_complete": None,
                        "playback_start": None,
                        "playback_end": None,
                        "errors": []
                    }

        # Retrieve current turn record
        timeline = self._timelines.get((sid, tid))
        if not timeline:
            return

        # Populate stage times
        if etype == "stt_final":
            timeline["stt_end"] = ts
            if timeline["stt_start"] is None:
                timeline["stt_start"] = timeline["vad_triggered_at"] or ts
        elif etype == "llm_request":
            timeline["llm_request_sent"] = ts
        elif etype == "llm_first_token":
            timeline["llm_first_token"] = ts
        elif etype == "llm_complete":
            timeline["llm_complete"] = ts
        elif etype == "tts_start":
            timeline["tts_request_sent"] = ts
        elif etype == "tts_chunk":
            if timeline["tts_first_chunk"] is None:
                timeline["tts_first_chunk"] = ts
        elif etype == "tts_complete":
            timeline["tts_complete"] = ts
        elif etype == "playback_start":
            timeline["playback_start"] = ts
            if timeline["tts_first_chunk"] is None:
                timeline["tts_first_chunk"] = ts
        elif etype == "playback_end":
            timeline["playback_end"] = ts

        # Record error and skip events
        is_error_or_skip = (
            etype == "error" or 
            "skipped" in etype or 
            etype == "cancellation"
        )
        if is_error_or_skip:
            timeline["errors"].append({
                "event": etype,
                "timestamp": ts,
                "detail": data
            })

        # If turn complete, calculate gaps, write log line, and discard from memory
        if etype == "turn_complete":
            if timeline["playback_end"] is None:
                timeline["playback_end"] = ts
            self._write_timeline(sid, tid)

    def _flush_previous_turns(self, session_id, current_turn_id):
        """Finds any older active turn timelines for this session and flushes them
        as they are now obsolete."""
        keys_to_flush = []
        for (sid, tid) in list(self._timelines.keys()):
            if sid == session_id:
                is_older = False
                if str(tid).isdigit() and str(current_turn_id).isdigit():
                    is_older = int(tid) < int(current_turn_id)
                elif tid != current_turn_id:
                    is_older = True
                
                if is_older:
                    keys_to_flush.append((sid, tid))

        for key in keys_to_flush:
            self._write_timeline(key[0], key[1], reason="superseded")

    def flush_session(self, session_id, reason="cancelled"):
        """Called when session is cancelled or shut down."""
        for (sid, tid) in list(self._timelines.keys()):
            if sid == session_id:
                self._write_timeline(sid, tid, reason=reason)

    def _write_timeline(self, session_id, turn_id, reason=None):
        timeline = self._timelines.pop((session_id, turn_id), None)
        if not timeline:
            return

        timeline["cancellation_reason"] = reason

        if reason:
            timeline["errors"].append({
                "event": f"timeline_flushed_{reason}",
                "timestamp": time.time(),
                "detail": {"message": f"Turn timeline flushed because of: {reason}"}
            })

        # Calculate gaps
        def diff_ms(t1, t2):
            if t1 is not None and t2 is not None:
                return round((t2 - t1) * 1000.0, 2)
            return None

        gaps = {
            "vad_to_stt_start_ms": diff_ms(timeline.get("vad_triggered_at"), timeline.get("stt_start")),
            "stt_start_to_stt_end_ms": diff_ms(timeline.get("stt_start"), timeline.get("stt_end")),
            "stt_end_to_llm_request_ms": diff_ms(timeline.get("stt_end"), timeline.get("llm_request_sent")),
            "llm_request_to_first_token_ms": diff_ms(timeline.get("llm_request_sent"), timeline.get("llm_first_token")),
            "llm_first_token_to_complete_ms": diff_ms(timeline.get("llm_first_token"), timeline.get("llm_complete")),
            "llm_complete_to_tts_request_ms": diff_ms(timeline.get("llm_complete"), timeline.get("tts_request_sent")),
            "tts_request_to_first_chunk_ms": diff_ms(timeline.get("tts_request_sent"), timeline.get("tts_first_chunk")),
            "tts_first_chunk_to_complete_ms": diff_ms(timeline.get("tts_first_chunk"), timeline.get("tts_complete")),
            "tts_complete_to_playback_start_ms": diff_ms(timeline.get("tts_complete"), timeline.get("playback_start")),
            "playback_start_to_end_ms": diff_ms(timeline.get("playback_start"), timeline.get("playback_end")),
            "total_turn_latency_ms": diff_ms(timeline.get("vad_triggered_at"), timeline.get("playback_end"))
        }

        timeline["gaps"] = gaps
        self.logger.info(json.dumps(timeline))


# Global singleton
telemetry_bus = TelemetryBus()
