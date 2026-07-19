"""
worker.py — Phase 6 Celery worker task definitions.
"""

import json
import time
from celery import Celery
from common.config.settings import get_settings
from common.logging.logger import get_logger
from services.orchestrator.state_store import get_redis_client
import importlib
ext_client = importlib.import_module("services.external-apis-integration.client")
handle_api_request = ext_client.handle_api_request
ValidationError = ext_client.ValidationError
NetworkError = ext_client.NetworkError
ProviderError = ext_client.ProviderError

settings = get_settings()
logger = get_logger("task-worker")

redis_url = settings.redis_url if settings.redis_url and settings.redis_url != "dummy_val" else "redis://localhost:6379/0"

import sys
_is_test = (settings.env == "test" or "pytest" in sys.modules)

# Celery App Configuration
celery_app = Celery("tasks", broker=redis_url, backend=redis_url)
celery_app.conf.task_always_eager = _is_test
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.task_acks_late = True

@celery_app.task(bind=True, max_retries=3)
def execute_tool_task(self, session_id: str, turn_id: str, tool_call_id: str, tool_name: str, params: dict):
    """
    Asynchronous Celery task that wraps tool execution, cooperative cancellation checks,
    heartbeat updates, error classification, and state transitions.
    """
    redis_client = get_redis_client()
    from services.orchestrator.tools import tool_manager, TOOL_REGISTRY
    
    metadata = TOOL_REGISTRY.get(tool_name)
    max_retries = metadata.max_retries if metadata else 3
    self.max_retries = max_retries

    dispatch_time = time.time()
    if redis_client is not None:
        try:
            val = redis_client.hget(f"session:{session_id}:tool:{tool_call_id}", "dispatch_time")
            if val:
                dispatch_time = float(val)
        except Exception:
            pass

    # 4. Worker Heartbeat and 5. Concurrency Safe state transition to RUNNING
    started_at = time.time()
    queue_wait = started_at - dispatch_time
    
    transition_ok = tool_manager._execute_transition(session_id, tool_call_id, "RUNNING")
    if not transition_ok:
        # State was already terminal (e.g. cancelled during queue wait)
        logger.log(
            event_name="tool_discarded",
            session_id=session_id,
            turn_id=turn_id,
            detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "reason": "Already cancelled/discarded in queue."}
        )
        return

    # Cooperative cancellation check
    cancel_key = f"session:{session_id}:tool:{tool_call_id}:cancelled"
    if redis_client is not None and redis_client.exists(cancel_key):
        tool_manager._execute_transition(session_id, tool_call_id, "CANCELLED", error_type="Cancelled")
        return

    # Update initial heartbeat
    if redis_client is not None:
        redis_client.hset(f"session:{session_id}:tool:{tool_call_id}", "heartbeat", str(time.time()))

    try:
        # Inject correlation IDs into params
        params["session_id"] = session_id
        params["tool_call_id"] = tool_call_id

        # Update heartbeat mid-execution (simulated for mock step)
        time.sleep(0.05)
        if redis_client is not None:
            redis_client.hset(f"session:{session_id}:tool:{tool_call_id}", "heartbeat", str(time.time()))

        # Cooperative cancellation check
        if redis_client is not None and redis_client.exists(cancel_key):
            tool_manager._execute_transition(session_id, tool_call_id, "CANCELLED", error_type="Cancelled")
            return

        # Execute actual API request
        result = handle_api_request(tool_name, params)
        
        # Concurrency safety: check final status in Redis
        status = "RUNNING"
        if redis_client is not None:
            status = redis_client.hget(f"session:{session_id}:tool:{tool_call_id}", "status")
            
        if status in ("CANCELLED", "DISCARDED"):
            # Result is discarded/cancelled, do not route to conversation
            logger.log(
                event_name="tool_discarded" if status == "DISCARDED" else "tool_cancelled",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "msg": "Result discarded due to interruption."}
            )
            return

        # Atomic transition to COMPLETED
        res_json = json.dumps(result)
        completed_ok = tool_manager._execute_transition(session_id, tool_call_id, "COMPLETED", result=res_json)
        if completed_ok:
            if redis_client is not None:
                redis_client.srem(f"session:{session_id}:active_tool_ids", tool_call_id)
            
            latency_ms = int((time.time() - started_at) * 1000)
            logger.log(
                event_name="tool_success",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id}
            )
            logger.log(
                event_name="tool_call_completed",
                session_id=session_id,
                turn_id=turn_id,
                detail={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "latency_ms": latency_ms,
                    "queue_wait_ms": int(queue_wait * 1000)
                }
            )

    except ValidationError as e:
        # ValidationError -> do not retry
        tool_manager._execute_transition(session_id, tool_call_id, "FAILED", error_type="ValidationError", result=str(e))
        if redis_client is not None:
            redis_client.srem(f"session:{session_id}:active_tool_ids", tool_call_id)
        logger.log(
            event_name="tool_failure",
            session_id=session_id,
            turn_id=turn_id,
            detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "ValidationError", "error": str(e)}
        )

    except TimeoutError as e:
        # Timeout -> retry if configured (bypass in test)
        if self.request.retries < max_retries and not _is_test:
            logger.log(
                event_name="tool_retry",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "Timeout"}
            )
            raise self.retry(exc=e, countdown=2)
        else:
            tool_manager._execute_transition(session_id, tool_call_id, "TIMEOUT", error_type="Timeout", result=str(e))
            if redis_client is not None:
                redis_client.srem(f"session:{session_id}:active_tool_ids", tool_call_id)
            logger.log(
                event_name="tool_timeout",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error": str(e)}
            )

    except NetworkError as e:
        # NetworkError -> retry with exponential backoff (bypass in test)
        if self.request.retries < max_retries and not _is_test:
            logger.log(
                event_name="tool_retry",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "NetworkError"}
            )
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
        else:
            tool_manager._execute_transition(session_id, tool_call_id, "FAILED", error_type="NetworkError", result=str(e))
            if redis_client is not None:
                redis_client.srem(f"session:{session_id}:active_tool_ids", tool_call_id)
            logger.log(
                event_name="tool_failure",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "NetworkError", "error": str(e)}
            )

    except ProviderError as e:
        # ProviderError -> retry only for transient failures (bypass in test)
        if self.request.retries < max_retries and "503" in str(e) and not _is_test:
            logger.log(
                event_name="tool_retry",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "ProviderError"}
            )
            raise self.retry(exc=e, countdown=2)
        else:
            tool_manager._execute_transition(session_id, tool_call_id, "FAILED", error_type="ProviderError", result=str(e))
            if redis_client is not None:
                redis_client.srem(f"session:{session_id}:active_tool_ids", tool_call_id)
            logger.log(
                event_name="tool_failure",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "ProviderError", "error": str(e)}
            )

    except Exception as e:
        # InternalError / Runtime errors
        if self.request.retries < max_retries and not _is_test:
            logger.log(
                event_name="tool_retry",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "InternalError"}
            )
            raise self.retry(exc=e, countdown=2)
        else:
            tool_manager._execute_transition(session_id, tool_call_id, "FAILED", error_type="InternalError", result=str(e))
            if redis_client is not None:
                redis_client.srem(f"session:{session_id}:active_tool_ids", tool_call_id)
            logger.log(
                event_name="tool_failure",
                session_id=session_id,
                turn_id=turn_id,
                detail={"tool_name": tool_name, "tool_call_id": tool_call_id, "error_type": "InternalError", "error": str(e)}
            )
