import json
import threading
from common.config.settings import get_settings
from common.logging.logger import get_logger

logger = get_logger("state-store")

# In-memory database fallback for testing/offline mode
_memory_db = {}
_memory_db_access = {}
_memory_lock = threading.Lock()
MAX_MEMORY_SESSIONS = 100
MEMORY_TTL = 7200  # 2 hours (7200s)


def _cleanup_memory_db():
    """Prunes expired or least recently used sessions from Python RAM to prevent memory leaks."""
    import time
    now = time.time()
    with _memory_lock:
        # 1. Remove sessions idle for more than 2 hours
        expired_keys = [k for k, last_time in _memory_db_access.items() if now - last_time > MEMORY_TTL]
        for k in expired_keys:
            _memory_db.pop(k, None)
            _memory_db_access.pop(k, None)
        
        # 2. Enforce capacity limit (MAX_MEMORY_SESSIONS = 100) using LRU strategy
        if len(_memory_db) > MAX_MEMORY_SESSIONS:
            sorted_sessions = sorted(_memory_db_access.items(), key=lambda x: x[1])
            to_evict = len(_memory_db) - MAX_MEMORY_SESSIONS
            for k, _ in sorted_sessions[:to_evict]:
                _memory_db.pop(k, None)
                _memory_db_access.pop(k, None)


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
    except (ImportError, ModuleNotFoundError):
        return None

    try:
        
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


_local_redis_client = None
_cloud_redis_client = None
_local_redis_failed = False
_cloud_redis_failed = False


def get_local_redis_client():
    """Retrieve or build a connection to the local standalone Redis instance on localhost:6379."""
    global _local_redis_client, _local_redis_failed
    if _local_redis_client is not None:
        return _local_redis_client
    if _local_redis_failed:
        return None
    try:
        import redis
        client = redis.from_url(
            "redis://127.0.0.1:6379",
            decode_responses=True,
            socket_timeout=1.0,
            socket_connect_timeout=1.0,
        )
        client.ping()
        _local_redis_client = client
        return client
    except Exception:
        _local_redis_failed = True
        return None


def get_cloud_redis_client():
    """Retrieve or build a connection to the remote configured Redis Cloud instance."""
    global _cloud_redis_client, _cloud_redis_failed
    if _cloud_redis_client is not None:
        return _cloud_redis_client
    if _cloud_redis_failed:
        return None
    try:
        client = get_redis_client()
        if client is not None:
            _cloud_redis_client = client
            return client
    except Exception:
        pass
    _cloud_redis_failed = True
    return None


def save_turn(session_id: str, turn_id: str, role: str, content: str):
    """Write an individual user or assistant speech turn to the session's history hierarchically."""
    import time
    new_message = {"role": role, "content": content}
    
    # 1. Tier 1: Write to local RAM dictionary immediately (fastest read path)
    with _memory_lock:
        if session_id not in _memory_db:
            _memory_db[session_id] = []
        _memory_db[session_id].append(new_message)
        _memory_db_access[session_id] = time.time()
    _cleanup_memory_db()

    # 3. Tier 3: Sync to Redis Cloud if active
    cloud_client = get_cloud_redis_client()
    cloud_success = False
    
    # 2. Tier 2: Sync to local Redis if active
    local_client = get_local_redis_client()
    local_success = False
    if local_client is not None:
        key = f"session:{session_id}:history"
        try:
            local_client.rpush(key, json.dumps(new_message))
            # Expire local Redis keys in 2 hours if Cloud Redis is active, or 24 hours if standalone
            local_ttl = 7200 if cloud_client is not None else 86400
            local_client.expire(key, local_ttl)
            local_success = True
        except Exception:
            pass

    if cloud_client is not None and cloud_client != local_client:
        key = f"session:{session_id}:history"
        try:
            cloud_client.rpush(key, json.dumps(new_message))
            cloud_client.expire(key, 86400)
            cloud_success = True
        except Exception:
            pass

    logger.log(
        event_name="state_update",
        session_id=session_id,
        turn_id=turn_id,
        detail={
            "role": role,
            "content_preview": content[:30],
            "backend": f"memory (local_redis={local_success}, cloud_redis={cloud_success})"
        }
    )


def load_history(session_id: str) -> list[dict]:
    """Retrieve complete list of turns hierarchically (RAM -> Redis Cloud -> Local Redis)."""
    import time
    # 1. Tier 1: Return from Python RAM dictionary instantly (0ms read latency)
    with _memory_lock:
        if session_id in _memory_db and len(_memory_db[session_id]) > 0:
            import copy
            _memory_db_access[session_id] = time.time()
            return copy.deepcopy(_memory_db[session_id])
    _cleanup_memory_db()

    # 2. Tier 3: If cold start, fetch from Redis Cloud (Source of Truth)
    cloud_client = get_cloud_redis_client()
    local_client = get_local_redis_client()
    key = f"session:{session_id}:history"
    
    if cloud_client is not None:
        try:
            history_data = cloud_client.lrange(key, 0, -1)
            if history_data:
                history = [json.loads(msg) for msg in history_data]
                _memory_db[session_id] = history
                _memory_db_access[session_id] = time.time()
                _cleanup_memory_db()
                # Clear local Redis key if Cloud Redis is configured and has data
                if local_client is not None and local_client != cloud_client:
                    try:
                        local_client.delete(key)
                    except Exception:
                        pass
                return history
        except Exception:
            pass

    # 3. Tier 2: Fetch from Local Redis fallback
    if local_client is not None:
        try:
            history_data = local_client.lrange(key, 0, -1)
            if history_data:
                history = [json.loads(msg) for msg in history_data]
                _memory_db[session_id] = history
                _memory_db_access[session_id] = time.time()
                _cleanup_memory_db()
                return history
        except Exception:
            pass

    import copy
    return copy.deepcopy(_memory_db.get(session_id, []))


def clear_session(session_id: str):
    """Clean up and delete all records associated with a session across all tiers."""
    if session_id in _memory_db:
        del _memory_db[session_id]
    if session_id in _memory_db_access:
        del _memory_db_access[session_id]

    key = f"session:{session_id}:history"

    local_client = get_local_redis_client()
    if local_client is not None:
        try:
            local_client.delete(key)
        except Exception:
            pass

    cloud_client = get_cloud_redis_client()
    if cloud_client is not None:
        try:
            cloud_client.delete(key)
        except Exception:
            pass

    try:
        from services.orchestrator.cache_client import clear_session_cache
        clear_session_cache(session_id)
    except Exception:
        pass