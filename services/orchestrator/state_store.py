import json
from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger("state-store")

# In-memory database fallback for testing/offline mode
_memory_db = {}

# Singleton Redis client
_redis_client = None
_redis_logged_error = False


def get_redis_client():
    """Build and verify a connection to Redis if configured and enabled.
    
    Returns a singleton Redis client with proper production settings:
    - Connection pooling
    - Socket timeouts
    - Retry on timeout
    - Health check interval
    - TLS support for rediss:// URLs
    """
    global _redis_client, _redis_logged_error
    
    if _redis_client is not None:
        return _redis_client
    
    settings = get_settings()
    
    # In test mode or when redis_url is empty/placeholder, bypass Redis
    if settings.env == "test" or not settings.redis_url or settings.redis_url == "dummy_val":
        logger.log(
            event_name="state_store_bypass",
            session_id="system",
            turn_id="system",
            detail={"msg": "Redis bypassed (test mode or no URL)"}
        )
        return None
    
    try:
        import redis
        from redis.retry import Retry
        from redis.backoff import ExponentialBackoff
        
        # Parse URL to determine if TLS is needed
        redis_url = settings.redis_url.strip().strip("'\"")
        if redis_url and not any(redis_url.startswith(s) for s in ["redis://", "rediss://", "unix://"]):
            redis_url = "redis://" + redis_url
        use_ssl = redis_url.startswith("rediss://")
        
        # Create client with production-grade settings
        # redis.from_url handles SSL automatically for rediss:// URLs
        conn_kwargs = {
            "decode_responses": True,
            # Connection pooling
            "max_connections": 20,
            # Timeouts
            "socket_timeout": 5.0,
            "socket_connect_timeout": 5.0,
            # Retry
            "retry": Retry(ExponentialBackoff(cap=10, base=0.1), 3),
            "retry_on_timeout": True,
            # Health checks
            "health_check_interval": 30,
        }
        if use_ssl:
            conn_kwargs["ssl_cert_reqs"] = None
            
        client = redis.from_url(redis_url, **conn_kwargs)
        
        # Verify connection viability
        client.ping()
        
        _redis_client = client
        
        logger.log(
            event_name="state_store_connected",
            session_id="system",
            turn_id="system",
            detail={
                "host": client.connection_pool.connection_kwargs.get("host"),
                "port": client.connection_pool.connection_kwargs.get("port"),
                "tls": use_ssl,
                "pool_size": 20,
            }
        )
        return client
        
    except redis.AuthenticationError as e:
        if not _redis_logged_error:
            _redis_logged_error = True
            logger.log(
                event_name="state_store_connection_failed",
                session_id="system",
                turn_id="system",
                detail={"error": str(e), "msg": "Redis authentication failed. Check password."}
            )
        if settings.env != "test":
            raise
        return None
    except redis.ConnectionError as e:
        if not _redis_logged_error:
            _redis_logged_error = True
            logger.log(
                event_name="state_store_connection_failed",
                session_id="system",
                turn_id="system",
                detail={"error": str(e), "msg": "Redis connection failed (timeout/refused)."}
            )
        if settings.env != "test":
            raise
        return None
    except redis.InvalidResponse as e:
        if not _redis_logged_error:
            _redis_logged_error = True
            logger.log(
                event_name="state_store_connection_failed",
                session_id="system",
                turn_id="system",
                detail={"error": str(e), "msg": "Redis protocol error (wrong port/TLS?)."}
            )
        if settings.env != "test":
            raise
        return None
    except Exception as e:
        if not _redis_logged_error:
            _redis_logged_error = True
            logger.log(
                event_name="state_store_connection_failed",
                session_id="system",
                turn_id="system",
                detail={"error": str(e), "msg": "Redis connection failed. Falling back to memory-store."}
            )
        if settings.env != "test":
            raise
        return None


def close_redis_client():
    """Close the Redis connection pool on shutdown."""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
            logger.log(
                event_name="state_store_closed",
                session_id="system",
                turn_id="system",
                detail={"msg": "Redis connection pool closed"}
            )
        except Exception as e:
            logger.log(
                event_name="state_store_close_failed",
                session_id="system",
                turn_id="system",
                detail={"error": str(e)}
            )
        _redis_client = None


def save_turn(session_id: str, turn_id: str, role: str, content: str):
    """Write an individual user or assistant speech turn to the session's history."""
    client = get_redis_client()
    new_message = {"role": role, "content": content}
    
    if client is not None:
        key = f"session:{session_id}:history"
        try:
            client.rpush(key, json.dumps(new_message))
            client.expire(key, 86400)  # Expire after 24h to avoid leaks on Redis Cloud
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
            if get_settings().env != "test":
                raise
            
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
            if get_settings().env != "test":
                raise
            
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
        except Exception as e:
            if get_settings().env != "test":
                raise
    if session_id in _memory_db:
        del _memory_db[session_id]