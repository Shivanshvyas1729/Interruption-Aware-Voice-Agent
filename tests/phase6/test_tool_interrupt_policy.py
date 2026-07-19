import pytest
import time
import json
from services.orchestrator.tools import tool_manager, TOOL_REGISTRY
from services.orchestrator.state_store import get_redis_client, clear_session

def clear_all_session_keys(session_id: str):
    clear_session(session_id)
    client = get_redis_client()
    if client is not None:
        try:
            client.delete(f"session:{session_id}:active_tool_ids")
            keys = client.keys(f"session:{session_id}:*")
            if keys:
                client.delete(*keys)
        except Exception:
            pass
    tool_manager._memory_db.clear()

def test_tool_call_interruption_follows_policy_table():
    session_id = "test-phase6-session"
    clear_all_session_keys(session_id)

    # 1. Test CORRECTION interruption policy (non-cancelable tool like check_balance)
    res = tool_manager.invoke_tool(
        session_id=session_id,
        turn_id="1",
        tool_name="check_balance",
        params={"account_id": "acc_123"}
    )
    tool_call_id = res["tool_call_id"]
    
    # Simulate in-flight by writing status=RUNNING directly (bypassing eager completion)
    key = f"session:{session_id}:tool:{tool_call_id}"
    if tool_manager.redis_client is not None:
        tool_manager.redis_client.hset(key, "status", "RUNNING")
        tool_manager.redis_client.sadd(f"session:{session_id}:active_tool_ids", tool_call_id)
    else:
        tool_manager._memory_db[key]["status"] = "RUNNING"
    
    # Interrupt
    tool_manager.on_interruption_during_call(session_id, "correction")
    
    if tool_manager.redis_client is not None:
        status = tool_manager.redis_client.hget(key, "status")
        interruption_type = tool_manager.redis_client.hget(key, "interruption_type")
    else:
        status = tool_manager._memory_db[key]["status"]
        interruption_type = tool_manager._memory_db[key].get("interruption_type")
        
    assert status == "DISCARDED"
    assert interruption_type == "correction"

    # 2. Test TOPIC-CHANGE policy (cancelable tool like transfer_funds)
    clear_all_session_keys(session_id)
    res = tool_manager.invoke_tool(
        session_id=session_id,
        turn_id="1",
        tool_name="transfer_funds",
        params={"from_account": "acc_1", "to_account": "acc_2", "amount": 100}
    )
    tool_call_id = res["tool_call_id"]
    
    # Simulate in-flight
    key = f"session:{session_id}:tool:{tool_call_id}"
    if tool_manager.redis_client is not None:
        tool_manager.redis_client.hset(key, "status", "RUNNING")
        tool_manager.redis_client.sadd(f"session:{session_id}:active_tool_ids", tool_call_id)
    else:
        tool_manager._memory_db[key]["status"] = "RUNNING"
    
    # Interrupt
    tool_manager.on_interruption_during_call(session_id, "topic-change")
    
    if tool_manager.redis_client is not None:
        status = tool_manager.redis_client.hget(key, "status")
        interruption_type = tool_manager.redis_client.hget(key, "interruption_type")
    else:
        status = tool_manager._memory_db[key]["status"]
        interruption_type = tool_manager._memory_db[key].get("interruption_type")
        
    assert status == "CANCELLED"
    assert interruption_type == "topic-change"

    # 3. Test CLARIFICATION policy (continues running in background)
    clear_all_session_keys(session_id)
    res = tool_manager.invoke_tool(
        session_id=session_id,
        turn_id="1",
        tool_name="transfer_funds",
        params={"from_account": "acc_1", "to_account": "acc_2", "amount": 100}
    )
    tool_call_id = res["tool_call_id"]
    
    # Simulate in-flight
    key = f"session:{session_id}:tool:{tool_call_id}"
    if tool_manager.redis_client is not None:
        tool_manager.redis_client.hset(key, "status", "RUNNING")
        tool_manager.redis_client.sadd(f"session:{session_id}:active_tool_ids", tool_call_id)
    else:
        tool_manager._memory_db[key]["status"] = "RUNNING"
    
    # Interrupt
    tool_manager.on_interruption_during_call(session_id, "clarification")
    
    if tool_manager.redis_client is not None:
        status = tool_manager.redis_client.hget(key, "status")
    else:
        status = tool_manager._memory_db[key]["status"]
        
    # Remains RUNNING
    assert status == "RUNNING"

    # 4. Test STOP-CANCEL policy on cancelable transfer_funds
    clear_all_session_keys(session_id)
    res = tool_manager.invoke_tool(
        session_id=session_id,
        turn_id="1",
        tool_name="transfer_funds",
        params={"from_account": "acc_1", "to_account": "acc_2", "amount": 100}
    )
    tool_call_id = res["tool_call_id"]
    
    # Simulate in-flight
    key = f"session:{session_id}:tool:{tool_call_id}"
    if tool_manager.redis_client is not None:
        tool_manager.redis_client.hset(key, "status", "RUNNING")
        tool_manager.redis_client.sadd(f"session:{session_id}:active_tool_ids", tool_call_id)
    else:
        tool_manager._memory_db[key]["status"] = "RUNNING"
    
    # Interrupt
    tool_manager.on_interruption_during_call(session_id, "stop_cancel")
    
    if tool_manager.redis_client is not None:
        status = tool_manager.redis_client.hget(key, "status")
        interruption_type = tool_manager.redis_client.hget(key, "interruption_type")
    else:
        status = tool_manager._memory_db[key]["status"]
        interruption_type = tool_manager._memory_db[key].get("interruption_type")
        
    assert status == "CANCELLED"
    assert interruption_type == "stop_cancel"

    # 5. Test Parameter Validation Failure (ValidationError -> no retry)
    clear_all_session_keys(session_id)
    res = tool_manager.invoke_tool(
        session_id=session_id,
        turn_id="1",
        tool_name="check_balance",
        params={}
    )
    assert res["status"] == "FAILED"
    assert res["error_type"] == "ValidationError"

    # 6. Test Error Classification (Force NetworkError -> retry -> final FAILED)
    clear_all_session_keys(session_id)
    res = tool_manager.invoke_tool(
        session_id=session_id,
        turn_id="1",
        tool_name="check_balance",
        params={"account_id": "acc_123", "force_error": "NetworkError"}
    )
    tool_call_id = res["tool_call_id"]
    
    key = f"session:{session_id}:tool:{tool_call_id}"
    if tool_manager.redis_client is not None:
        status = tool_manager.redis_client.hget(key, "status")
        error_type = tool_manager.redis_client.hget(key, "error_type")
        assert status == "FAILED"
        assert error_type == "NetworkError"
