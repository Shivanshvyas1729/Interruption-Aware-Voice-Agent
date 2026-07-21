import asyncio


class CancelToken:
    __slots__ = ("_cancelled", "_reason", "_event")

    def __init__(self):
        self._cancelled = False
        self._reason = ""
        self._event = asyncio.Event()

    def cancel(self, reason: str = ""):
        self._cancelled = True
        self._reason = reason
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str:
        return self._reason

    async def wait(self):
        await self._event.wait()

    def reset(self):
        self._cancelled = False
        self._reason = ""
        self._event.clear()


_tokens: dict[str, CancelToken] = {}
_current_turn: dict[str, int] = {}


def get_cancel_token(session_id: str) -> CancelToken:
    if session_id not in _tokens:
        _tokens[session_id] = CancelToken()
    return _tokens[session_id]


def reset_cancel_token(session_id: str):
    tok = _tokens.get(session_id)
    if tok:
        tok.reset()


def cleanup_session(session_id: str) -> None:
    _tokens.pop(session_id, None)
    _current_turn.pop(session_id, None)
    # Lazy import to avoid circular dependency at module load time
    try:
        from services.orchestrator.cancellation_manager import cancellation_manager
        cancellation_manager.cleanup_session(session_id)
    except Exception:
        pass


def get_current_turn(session_id: str) -> int:
    return _current_turn.get(session_id, 0)


def set_current_turn(session_id: str, turn_id: int) -> None:
    _current_turn[session_id] = turn_id
