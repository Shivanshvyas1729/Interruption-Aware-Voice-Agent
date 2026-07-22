"""
services/orchestrator/tts_connection_manager.py — Dedicated Connection Lifecycle Manager.

Owns WebSocket connection pooling, thread-safe session registry, pre-warming,
in-flight race guards, per-session continuation flags, and idle socket reaping.
"""

import time
import asyncio
import threading
from typing import Any, Optional
from common.config.settings import get_settings
from common.logging.logger import get_logger
from services.orchestrator.tts_client import open_ws_context, close_ws_context

logger = get_logger("tts-connection-manager")

_connection_manager: Optional["TTSConnectionManager"] = None
_manager_lock = threading.Lock()


class TTSConnectionManager:
    """Thread-safe manager for Cartesia TTS WebSocket connections."""

    def __init__(self):
        self._lock = threading.Lock()
        self._ws_sessions: dict[str, tuple[Any, Any]] = {}
        self._last_accessed: dict[str, float] = {}
        self._in_flight_events: dict[str, threading.Event] = {}
        self._failed_continuation: set[str] = set()
        self._reaper_task: Optional[asyncio.Task] = None
        self._started = False

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Starts the idle socket reaper background task."""
        if self._started:
            return
        self._started = True
        try:
            active_loop = loop or asyncio.get_running_loop()
            self._reaper_task = active_loop.create_task(
                self._idle_reaper_loop(), name="tts-idle-reaper"
            )
        except RuntimeError:
            pass

    def shutdown(self) -> None:
        """Closes all open WebSockets and cancels background reaper."""
        if self._reaper_task and not self._reaper_task.done():
            self._reaper_task.cancel()
            self._reaper_task = None
        with self._lock:
            sessions = list(self._ws_sessions.items())
            self._ws_sessions.clear()
            self._last_accessed.clear()
            self._failed_continuation.clear()
            self._in_flight_events.clear()
        for session_id, (ws, _) in sessions:
            close_ws_context(ws, session_id, "manager_shutdown")
        self._started = False

    def acquire(self, session_id: str, turn_id: str) -> tuple[Any, Any]:
        """Thread-safe acquisition or creation of (ws, ctx) for session_id.
        Waits on in-flight pre-warm/connection events to prevent duplicate sockets."""
        with self._lock:
            if session_id in self._ws_sessions:
                self._last_accessed[session_id] = time.time()
                return self._ws_sessions[session_id]
            if session_id in self._in_flight_events:
                evt = self._in_flight_events[session_id]
                self._lock.release()
                try:
                    evt.wait(timeout=10.0)
                finally:
                    self._lock.acquire()
                if session_id in self._ws_sessions:
                    self._last_accessed[session_id] = time.time()
                    return self._ws_sessions[session_id]
            evt = threading.Event()
            self._in_flight_events[session_id] = evt

        try:
            ws, ctx = open_ws_context(session_id, turn_id)
            with self._lock:
                self._ws_sessions[session_id] = (ws, ctx)
                self._last_accessed[session_id] = time.time()
                evt.set()
                self._in_flight_events.pop(session_id, None)
            return ws, ctx
        except Exception:
            with self._lock:
                evt.set()
                self._in_flight_events.pop(session_id, None)
            raise

    def release(self, session_id: str, failed: bool = False, cancelled: bool = False) -> None:
        """Updates timestamp or tears down socket if failed/cancelled."""
        should_close = failed or cancelled
        if should_close:
            ws_tuple = None
            with self._lock:
                ws_tuple = self._ws_sessions.pop(session_id, None)
                self._last_accessed.pop(session_id, None)
            if ws_tuple:
                close_ws_context(ws_tuple[0], session_id, "release_failed")
        else:
            with self._lock:
                if session_id in self._ws_sessions:
                    self._last_accessed[session_id] = time.time()

    def cleanup(self, session_id: str) -> None:
        """Immediately closes connection upon client disconnect."""
        ws_tuple = None
        with self._lock:
            self._last_accessed.pop(session_id, None)
            self._failed_continuation.discard(session_id)
            ws_tuple = self._ws_sessions.pop(session_id, None)
        if ws_tuple:
            close_ws_context(ws_tuple[0], session_id, "session_cleanup")

    def prewarm(self, session_id: str, executor: Any) -> None:
        """Triggers sync prewarm on worker thread pool if connection not present."""
        with self._lock:
            if session_id in self._ws_sessions or session_id in self._in_flight_events:
                return
        settings = get_settings()
        api_key = settings.cartesia_api_key
        if not api_key or api_key == "dummy_val" or settings.env == "test":
            return
        try:
            self.acquire(session_id, "prewarm")
            logger.log("tts_ws_prewarmed", session_id, "system", detail={})
        except Exception as e:
            logger.log_error("tts_ws_prewarm_failed", session_id, "system", e)

    def mark_continuation_failed(self, session_id: str) -> None:
        """Marks continuation unsupported strictly for session_id."""
        with self._lock:
            self._failed_continuation.add(session_id)

    def is_continuation_failed(self, session_id: str) -> bool:
        """Checks if session_id is degraded to sentence fallback."""
        with self._lock:
            return session_id in self._failed_continuation

    def health_check(self) -> dict[str, Any]:
        """Returns connection pool health metrics."""
        with self._lock:
            return {
                "active_sockets": len(self._ws_sessions),
                "in_flight_connects": len(self._in_flight_events),
                "degraded_sessions": len(self._failed_continuation),
            }

    async def _idle_reaper_loop(self):
        while self._started:
            try:
                await asyncio.sleep(15.0)
            except asyncio.CancelledError:
                break
            self._reap_idle_sockets(idle_timeout_s=60.0)

    def _reap_idle_sockets(self, idle_timeout_s: float = 60.0) -> None:
        now = time.time()
        to_close = []
        with self._lock:
            for session_id, last_ts in list(self._last_accessed.items()):
                if now - last_ts > idle_timeout_s:
                    ws_tuple = self._ws_sessions.pop(session_id, None)
                    self._last_accessed.pop(session_id, None)
                    self._failed_continuation.discard(session_id)
                    if ws_tuple:
                        to_close.append((session_id, ws_tuple[0], last_ts))

        for sid, ws, last_ts in to_close:
            close_ws_context(ws, sid, "idle_timeout_reaper")
            logger.log("tts_ws_idle_reaped", sid, "system", detail={"idle_s": round(now - last_ts, 2)})


def get_connection_manager() -> TTSConnectionManager:
    """Returns global TTSConnectionManager singleton."""
    global _connection_manager
    with _manager_lock:
        if _connection_manager is None:
            _connection_manager = TTSConnectionManager()
        return _connection_manager
