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

    def push(self, event_type: str, data: dict = None, session_id: str = "", turn_id: str = ""):
        event = TelemetryEvent(event_type, data, session_id, turn_id)
        self._history.append(event)

        # Track per-session metrics automatically
        self._update_session_metrics(event)

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


# Global singleton
telemetry_bus = TelemetryBus()
