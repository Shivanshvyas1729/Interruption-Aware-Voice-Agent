import json
from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger("state-store")

# In-memory database fallback for testing/offline mode
_memory_db = {}

def get_redis_client():
    """Build and verify a connection to Redis if configured and enabled."""
    settings = get_settings()
    # In test mode or when redis_url is empty/placeholder, bypass Redis
    if settings.env == "test" or not settings.redis_url or settings.redis_url == "dummy_val":
        return None
    try:
        import redis
        client = redis.from_url(settings.redis_url, decode_responses=True)
        # Verify connection viability
        client.ping()
        return client
    except Exception as e:
        logger.log(
            event_name="state_store_connection_failed",
            session_id="system",
            turn_id="system",
            detail={"error": str(e), "msg": "Redis connection failed. Falling back to memory-store."}
        )
        return None

def save_turn(session_id: str, turn_id: str, role: str, content: str):
    """Write an individual user or assistant speech turn to the session's history."""
    client = get_redis_client()
    new_message = {"role": role, "content": content}
    
    if client is not None:
        key = f"session:{session_id}:history"
        try:
            client.rpush(key, json.dumps(new_message))
            logger.log(
                event_name="state_update",
                session_id=session_id,
                turn_id=turn_id,
                detail={"role": role, "content_preview": content[:30], "backend": "redis"}
            )
            return
        except Exception as e:
            logger.log(
                event_name="state_update_failed",
                session_id=session_id,
                turn_id=turn_id,
                detail={"error": str(e), "msg": "Failing over to memory-store."}
            )
            
    # In-memory database fallback
    if session_id not in _memory_db:
        _memory_db[session_id] = []
    _memory_db[session_id].append(new_message)
    logger.log(
        event_name="state_update",
        session_id=session_id,
        turn_id=turn_id,
        detail={"role": role, "content_preview": content[:30], "backend": "memory"}
    )

def load_history(session_id: str) -> list[dict]:
    """Retrieve the complete list of turns (messages) for the active session."""
    client = get_redis_client()
    if client is not None:
        key = f"session:{session_id}:history"
        try:
            history_data = client.lrange(key, 0, -1)
            history = [json.loads(msg) for msg in history_data]
            return history
        except Exception as e:
            logger.log(
                event_name="state_load_failed",
                session_id=session_id,
                turn_id="system",
                detail={"error": str(e), "msg": "Failing over to memory-store."}
            )
            
    # In-memory database fallback (return a deepcopy to simulate new objects like Redis JSON load)
    import copy
    return copy.deepcopy(_memory_db.get(session_id, []))

def clear_session(session_id: str):
    """Clean up and delete all records associated with a session."""
    client = get_redis_client()
    if client is not None:
        key = f"session:{session_id}:history"
        try:
            client.delete(key)
        except Exception:
            pass
    if session_id in _memory_db:
        del _memory_db[session_id]
