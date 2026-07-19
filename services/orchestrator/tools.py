"""
tools.py — Phase 6 Tool Manager and Registry.
"""

import json
import time
import uuid
from typing import Optional
from common.logging.logger import get_logger
from services.orchestrator.state_store import get_redis_client

logger = get_logger("tool-manager")

class ToolMetadata:
    def __init__(
        self,
        name: str,
        cancelable: bool = True,
        timeout: float = 10.0,
        max_retries: int = 3,
        idempotent: bool = True,
        supports_background: bool = True
    ):
        self.name = name
        self.cancelable = cancelable
        self.timeout = timeout
        self.max_retries = max_retries
        self.idempotent = idempotent
        self.supports_background = supports_background

TOOL_REGISTRY = {
    "check_balance": ToolMetadata(
        name="check_balance",
        cancelable=False,
        timeout=5.0,
        max_retries=3,
        idempotent=True,
        supports_background=False
    ),
    "transfer_funds": ToolMetadata(
        name="transfer_funds",
        cancelable=True,
        timeout=10.0,
        max_retries=1,
        idempotent=False,
        supports_background=True
    )
}

LUA_TRANSITION_SCRIPT = """
local key = KEYS[1]
local target_status = ARGV[1]
local error_type = ARGV[2]
local result = ARGV[3]
local interruption_type = ARGV[4]
local timestamp = ARGV[5]

local current_status = redis.call('HGET', key, 'status')
if not current_status then
    if target_status == 'QUEUED' or target_status == 'RUNNING' then
        redis.call('HSET', key, 'status', target_status)
        if target_status == 'RUNNING' then
            redis.call('HSET', key, 'started_at', timestamp)
        else
            redis.call('HSET', key, 'created_at', timestamp)
        end
        redis.call('EXPIRE', key, 86400)
        return 1
    end
    return 0
end

-- Terminal state validation: once terminal, no further transitions allowed
if current_status == 'COMPLETED' or current_status == 'FAILED' or current_status == 'CANCELLED' or current_status == 'DISCARDED' or current_status == 'TIMEOUT' then
    return 0
end

redis.call('HSET', key, 'status', target_status)
if error_type and error_type ~= '' then
    redis.call('HSET', key, 'error_type', error_type)
end
if result and result ~= '' then
    redis.call('HSET', key, 'result', result)
end
if interruption_type and interruption_type ~= '' then
    redis.call('HSET', key, 'interruption_type', interruption_type)
end

if target_status == 'RUNNING' then
    redis.call('HSET', key, 'started_at', timestamp)
elseif target_status == 'COMPLETED' or target_status == 'FAILED' or target_status == 'CANCELLED' or target_status == 'DISCARDED' or target_status == 'TIMEOUT' then
    redis.call('HSET', key, 'completed_at', timestamp)
end
return 1
"""

class ToolManager:
    def __init__(self):
        self.redis_client = get_redis_client()
        self._memory_db = {} # Fallback

    def _execute_transition(
        self,
        session_id: str,
        tool_call_id: str,
        target_status: str,
        error_type: Optional[str] = None,
        result: Optional[str] = None,
        interruption_type: Optional[str] = None
    ) -> bool:
        """Atomically transitions tool status in Redis using Lua script."""
        key = f"session:{session_id}:tool:{tool_call_id}"
        timestamp = str(time.time())
        err_str = error_type or ""
        res_str = result or ""
        int_str = interruption_type or ""
        
        if self.redis_client is not None:
            try:
                # Register/load Lua script
                script = self.redis_client.register_script(LUA_TRANSITION_SCRIPT)
                success = script(keys=[key], args=[target_status, err_str, res_str, int_str, timestamp])
                return bool(success)
            except Exception as e:
                logger.log(
                    event_name="tool_transition_failed",
                    session_id=session_id,
                    turn_id="system",
                    detail={"error": str(e), "tool_call_id": tool_call_id}
                )
                
        # In-memory database fallback
        if key not in self._memory_db:
            if target_status not in ("QUEUED", "RUNNING"):
                return False
            self._memory_db[key] = {
                "status": target_status,
                "created_at": timestamp if target_status == "QUEUED" else None,
                "started_at": timestamp if target_status == "RUNNING" else None,
            }
            return True
            
        curr = self._memory_db[key]
        if curr["status"] in ("COMPLETED", "FAILED", "CANCELLED", "DISCARDED", "TIMEOUT"):
            return False
            
        curr["status"] = target_status
        if err_str:
            curr["error_type"] = err_str
        if res_str:
            curr["result"] = res_str
        if int_str:
            curr["interruption_type"] = int_str
        if target_status in ("COMPLETED", "FAILED", "CANCELLED", "DISCARDED", "TIMEOUT"):
            curr["completed_at"] = timestamp
        elif target_status == "RUNNING":
            curr["started_at"] = timestamp
        return True

    def invoke_tool(self, session_id: str, turn_id: str, tool_name: str, params: dict) -> dict:
        """
        Validates parameters, generates a unique tool_call_id, and dispatches the execution task.
        """
        # 8. Security Validation
        if tool_name not in TOOL_REGISTRY:
            err_msg = f"Unauthorized or unknown tool: {tool_name}"
            logger.log(
                event_name="tool_failure",
                session_id=session_id,
                turn_id=turn_id,
                detail={"error_type": "ValidationError", "msg": err_msg}
            )
            return {"status": "FAILED", "error_type": "ValidationError", "error": err_msg}

        metadata = TOOL_REGISTRY[tool_name]
        
        # Parameter validation checks
        if tool_name == "check_balance" and "account_id" not in params:
            err_msg = "Parameter account_id is required."
            logger.log(
                event_name="tool_failure",
                session_id=session_id,
                turn_id=turn_id,
                detail={"error_type": "ValidationError", "msg": err_msg}
            )
            return {"status": "FAILED", "error_type": "ValidationError", "error": err_msg}
            
        # Generates a unique tool_call_id
        tool_call_id = f"tool_{uuid.uuid4().hex[:8]}"
        
        # 18. Idempotency checks
        if metadata.idempotent and self.redis_client is not None:
            # Check duplicate invocation using the same logical key
            dup_key = f"session:{session_id}:dup:{tool_name}:{json.dumps(params, sort_keys=True)}"
            if self.redis_client.set(dup_key, tool_call_id, nx=True, ex=3600) is None:
                # Retrieve existing tool call ID
                existing_id = self.redis_client.get(dup_key)
                logger.log(
                    event_name="tool_retry",
                    session_id=session_id,
                    turn_id=turn_id,
                    detail={"tool_name": tool_name, "tool_call_id": existing_id, "msg": "Duplicate call bypassed."}
                )
                return {"status": "QUEUED", "tool_call_id": existing_id, "is_duplicate": True}

        # Initialize State in Redis/Memory
        self._execute_transition(session_id, tool_call_id, "QUEUED")
        
        # Register in active tool index
        if self.redis_client is not None:
            self.redis_client.sadd(f"session:{session_id}:active_tool_ids", tool_call_id)
            self.redis_client.expire(f"session:{session_id}:active_tool_ids", 86400)
            
            # Save basic metadata to tool hash
            key = f"session:{session_id}:tool:{tool_call_id}"
            self.redis_client.hset(key, mapping={
                "tool_name": tool_name,
                "session_id": session_id,
                "turn_id": turn_id,
                "tool_call_id": tool_call_id,
                "cancelable": "1" if metadata.cancelable else "0",
                "dispatch_time": str(time.time())
            })
        else:
            key = f"session:{session_id}:tool:{tool_call_id}"
            if key in self._memory_db:
                self._memory_db[key].update({
                    "tool_name": tool_name,
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "tool_call_id": tool_call_id,
                    "cancelable": "1" if metadata.cancelable else "0",
                    "dispatch_time": str(time.time())
                })

        logger.log(
            event_name="tool_call_started",
            session_id=session_id,
            turn_id=turn_id,
            detail={"tool_name": tool_name, "tool_call_id": tool_call_id}
        )

        # Execution backend selection: Celery vs. synchronous test fallback
        from common.config.settings import get_settings
        settings = get_settings()
        
        import sys
        if settings.env == "test" or "pytest" in sys.modules or self.redis_client is None:
            # Synchronous execution fallback for testing without Celery queue
            from services.task_worker.worker import execute_tool_task
            try:
                res = execute_tool_task.apply(args=(session_id, turn_id, tool_call_id, tool_name, params))
                if res.failed():
                    print(f"DEBUG: Celery Eager task failed! Status: {res.status}")
                    print(f"DEBUG: Exception: {res.result}")
                    print(f"DEBUG: Traceback: {res.traceback}")
            except Exception as e:
                print(f"DEBUG: execute_tool_task.apply failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            # Asynchronous Celery execution
            from services.task_worker.worker import execute_tool_task
            celery_task = execute_tool_task.delay(session_id, turn_id, tool_call_id, tool_name, params)
            # Store Celery task_id in Redis hash for revoking
            self.redis_client.hset(f"session:{session_id}:tool:{tool_call_id}", "celery_task_id", celery_task.id)

        return {"status": "QUEUED", "tool_call_id": tool_call_id}

    def on_interruption_during_call(self, session_id: str, interruption_type: str):
        """
        Interrupts all active tool calls for the session and applies the policy table.
        """
        active_ids = []
        if self.redis_client is not None:
            active_ids = list(self.redis_client.smembers(f"session:{session_id}:active_tool_ids"))
        else:
            prefix = f"session:{session_id}:tool:"
            active_ids = [
                k[len(prefix):] for k, v in self._memory_db.items()
                if k.startswith(prefix) and v.get("status") in ("QUEUED", "RUNNING")
            ]
        
        for tool_call_id in active_ids:
            key = f"session:{session_id}:tool:{tool_call_id}"
            if self.redis_client is not None:
                tool_data = self.redis_client.hgetall(key)
            else:
                tool_data = self._memory_db.get(key, {})

            tool_name = tool_data.get("tool_name", "unknown")
            cancelable = tool_data.get("cancelable") == "1"
            celery_task_id = tool_data.get("celery_task_id")
            
            policy = "finish_silently"
            target_status = "DISCARDED"

            # Apply Interruption Policy Table
            if interruption_type in ("correction", "stop_cancel", "stop-cancel"):
                if cancelable:
                    policy = "abort"
                    target_status = "CANCELLED"
                else:
                    policy = "finish_silently"
                    target_status = "DISCARDED"
            elif interruption_type in ("topic_change", "topic-change"):
                if cancelable:
                    policy = "abort"
                    target_status = "CANCELLED"
                else:
                    policy = "finish_silently"
                    target_status = "DISCARDED"
            elif interruption_type == "clarification":
                policy = "continue_background"
                target_status = "RUNNING" # Keeps running, does not cancel or discard
            elif interruption_type in ("add_on", "add-on"):
                policy = "queue_follow_up"
                target_status = "RUNNING"

            logger.log(
                event_name="tool_call_interrupted",
                session_id=session_id,
                turn_id=tool_data.get("turn_id", "system"),
                detail={
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "interruption_type": interruption_type,
                    "policy_applied": policy
                }
            )

            # Atomic transition and interruption reason preservation
            if target_status in ("CANCELLED", "DISCARDED"):
                self._execute_transition(
                    session_id=session_id,
                    tool_call_id=tool_call_id,
                    target_status=target_status,
                    interruption_type=interruption_type
                )
                
                # SREM from active index
                if self.redis_client is not None:
                    self.redis_client.srem(f"session:{session_id}:active_tool_ids", tool_call_id)
                    
                # Cooperative Cancellation Flag Set
                if self.redis_client is not None:
                    self.redis_client.set(f"session:{session_id}:tool:{tool_call_id}:cancelled", "1", ex=3600)
                
                # Celery Revoke if active Celery ID is registered
                if celery_task_id and self.redis_client is not None:
                    try:
                        from services.task_worker.worker import celery_app
                        celery_app.control.revoke(celery_task_id, terminate=True)
                    except Exception:
                        pass
                
                # Emit metrics
                logger.log(
                    event_name="tool_discarded" if target_status == "DISCARDED" else "tool_cancelled",
                    session_id=session_id,
                    turn_id="system",
                    detail={"tool_name": tool_name, "tool_call_id": tool_call_id}
                )

# Singleton instance
tool_manager = ToolManager()
