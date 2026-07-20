import asyncio
from common.logging.logger import get_logger

logger = get_logger("cancellation-manager")

class CancellationManager:
    def __init__(self):
        # Maps session_id -> set of active asyncio.Task objects
        self._active_tasks = {}
        # Thread-safe set of currently cancelled session IDs
        self._cancelled_sessions = set()

    def register_task(self, session_id: str, task: asyncio.Task):
        """Register a running asyncio task so it can be canceled on user interruption."""
        if session_id not in self._active_tasks:
            self._active_tasks[session_id] = set()
        
        self._active_tasks[session_id].add(task)
        
        # Discard the task from active tracking once it finishes naturally
        task.add_done_callback(lambda t: self._active_tasks.get(session_id, set()).discard(t))

    def cancel_session(self, session_id: str, reason: str = "user_interruption"):
        """Cancel all registered asyncio tasks for the session and set cancellation flags."""
        self._cancelled_sessions.add(session_id)
        
        tasks_to_cancel = list(self._active_tasks.get(session_id, []))
        
        logger.log(
            event_name="cancellation_triggered",
            session_id=session_id,
            turn_id="system",
            detail={"reason": reason, "cancelled_task_count": len(tasks_to_cancel)}
        )
        
        # Abort all registered asynchronous jobs immediately
        for task in tasks_to_cancel:
            if not task.done():
                task.cancel()
                
        if session_id in self._active_tasks:
            self._active_tasks[session_id].clear()

    def is_cancelled(self, session_id: str) -> bool:
        """Check if the session is currently flagged as cancelled."""
        return session_id in self._cancelled_sessions

    def reset_session(self, session_id: str):
        """Clear cancellation flags for a session to allow new turns to process."""
        if session_id in self._cancelled_sessions:
            self._cancelled_sessions.remove(session_id)
            logger.log(
                event_name="cancellation_reset",
                session_id=session_id,
                turn_id="system",
                detail={"msg": "Session cancellation flag cleared for new turn."}
            )

    def cleanup_session(self, session_id: str):
        """Remove session references on disconnect to prevent memory leaks."""
        self._cancelled_sessions.discard(session_id)
        self._active_tasks.pop(session_id, None)

# Global singleton instance
cancellation_manager = CancellationManager()
