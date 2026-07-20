import asyncio
import time
import sys
import uuid
from unittest.mock import patch, MagicMock
from services.orchestrator.async_pipeline import get_pipeline, get_cancel_token
from common.config.settings import get_settings
from services.orchestrator import context_merge, tools, cache_client, failover
from services.orchestrator.state_store import get_redis_client, clear_session

async def test_integration():
    settings = get_settings()
    orig_env = settings.env
    settings.env = "test"
    
    # 0. Initialize Pipeline
    pipeline = get_pipeline()
    pipeline.start()
    
    # Generate unique session ID for this run to avoid cache / tool idempotency interference
    session_id = f"test-int-{uuid.uuid4().hex[:6]}"
    playback_queue = asyncio.Queue()
    pipeline.register_playback_client(session_id, playback_queue)
    
    # Track context_merge.resolve calls
    resolve_calls = []
    orig_resolve = context_merge.resolve
    def mock_resolve(sid, spoken, unspoken, itype):
        resolve_calls.append((sid, spoken, unspoken, itype))
        return orig_resolve(sid, spoken, unspoken, itype)
    
    # Track tool_manager.on_interruption_during_call calls
    tool_interrupt_calls = []
    orig_on_interrupt = tools.tool_manager.on_interruption_during_call
    def mock_on_interrupt(sid, itype):
        tool_interrupt_calls.append((sid, itype))
        return orig_on_interrupt(sid, itype)
        
    try:
        with patch("services.orchestrator.context_merge.resolve", new=mock_resolve), \
             patch.object(tools.tool_manager, "on_interruption_during_call", new=mock_on_interrupt), \
             patch("services.task_worker.worker.execute_tool_task.apply") as mock_apply:
             
            # Test 1: Mid-turn cancellation & Context Merging
            # Reset cache/tokens
            get_cancel_token(session_id).reset()
            
            # Submit a long reply prompt
            # We want to sleep during TTS synthesis to allow playback to start and then interrupt
            print("\n--- Test 1: Interruption & Context Merging ---")
            await pipeline.submit_transcript(session_id, "Explain the solar system in detail", 1)
            
            # Wait for some playback chunks to be generated/sent (simulates spoken words)
            # Sleep 0.4s to ensure LLM (50ms) and TTS (50ms) are done, and Playback is actively running
            await asyncio.sleep(0.4)
            
            # Trigger cancellation (barge_in)
            await pipeline.submit_cancel(session_id, "barge_in")
            await asyncio.sleep(0.3)
            
            # Verify context_merge.resolve was called
            assert len(resolve_calls) > 0, "context_merge.resolve was not called!"
            sid, spoken, unspoken, itype = resolve_calls[0]
            print(f"context_merge.resolve called: session={sid}, spoken={spoken}, unspoken={unspoken}, type={itype}")
            assert itype == "stop_cancel", f"Expected type 'stop_cancel', got {itype}"
            # Verify non-trivial split (since text response has words and we slept, spoken or unspoken should be non-empty)
            assert len(spoken) > 0 or len(unspoken) > 0, "No words tracked for merge!"
            print("Test 1: PASSED")

            # Test 2: Semantic Cache Lookup & Store
            print("\n--- Test 2: Semantic Cache ---")
            # Clear session to ensure we start fresh on Turn 1
            clear_session(session_id)
            pipeline.fsm._get_session(session_id).turn_id = 0
            get_cancel_token(session_id).reset()
            # Clear queue
            while not playback_queue.empty():
                playback_queue.get_nowait()
                
            t_start1 = time.time()
            await pipeline.submit_transcript(session_id, "What is the distance to Mars?", 1)
            # Wait for completion
            while True:
                item = await playback_queue.get()
                if isinstance(item, dict) and item.get("type") == "llm_response":
                    break
            dur1 = (time.time() - t_start1) * 1000
            
            # Reset history and turn ID to turn 1 so history matches perfectly for cache lookup
            clear_session(session_id)
            pipeline.fsm._get_session(session_id).turn_id = 0
            get_cancel_token(session_id).reset()
            
            t_start2 = time.time()
            await pipeline.submit_transcript(session_id, "What is the distance to Mars?", 1)
            while True:
                item = await playback_queue.get()
                if isinstance(item, dict) and item.get("type") == "llm_response":
                    break
            dur2 = (time.time() - t_start2) * 1000
            
            print(f"First call duration: {dur1:.1f}ms, Second (cached) call duration: {dur2:.1f}ms")
            # Cached response should be served almost instantly (<20ms compared to mock sleep 50ms)
            assert dur2 < dur1, f"Cached run was not faster! {dur2:.1f}ms vs {dur1:.1f}ms"
            print("Test 2: PASSED")

            # Test 3: Circuit Breaker Failover Router
            print("\n--- Test 3: Circuit Breaker Failover ---")
            get_cancel_token(session_id).reset()
            # Submit a prompt containing force_failover and check that OpenAI fallback is used
            # Clear queue
            while not playback_queue.empty():
                playback_queue.get_nowait()
            await pipeline.submit_transcript(session_id, "force_failover", 4)
            while True:
                item = await playback_queue.get()
                if isinstance(item, dict) and item.get("type") == "llm_response":
                    print(f"Fallback response: {item.get('text')}")
                    assert "welcome" in item.get('text', "").lower(), "Unexpected fallback response text"
                    break
            print("Test 3: PASSED")

            # Test 4: Tool Policy Interruption
            print("\n--- Test 4: Tool Interruption ---")
            get_cancel_token(session_id).reset()
            # Mock a tool call active on session
            # check_balance is non-cancelable (cancelable=False)
            res_balance = tools.tool_manager.invoke_tool(session_id, "5", "check_balance", {"account_id": "123"})
            # transfer_funds is cancelable (cancelable=True)
            res_funds = tools.tool_manager.invoke_tool(session_id, "5", "transfer_funds", {"account_id": "123", "amount": 100})
            
            # Trigger cancel
            await pipeline.submit_cancel(session_id, "correction")
            await asyncio.sleep(0.1)
            
            assert len(tool_interrupt_calls) > 0, "tool_manager.on_interruption_during_call was not called!"
            print(f"tool_manager.on_interruption_during_call called: {tool_interrupt_calls[0]}")
            
            # Check statuses in database / memory
            def decode_val(val):
                if isinstance(val, bytes):
                    return val.decode('utf-8')
                return str(val)

            r = tools.tool_manager.redis_client
            if r is not None:
                check_balance_data = {decode_val(k): decode_val(v) for k, v in r.hgetall(f"session:{session_id}:tool:{res_balance['tool_call_id']}").items()}
                transfer_funds_data = {decode_val(k): decode_val(v) for k, v in r.hgetall(f"session:{session_id}:tool:{res_funds['tool_call_id']}").items()}
            else:
                check_balance_data = tools.tool_manager._memory_db.get(f"session:{session_id}:tool:{res_balance['tool_call_id']}", {})
                transfer_funds_data = tools.tool_manager._memory_db.get(f"session:{session_id}:tool:{res_funds['tool_call_id']}", {})
            
            check_balance_status = check_balance_data.get("status")
            transfer_funds_status = transfer_funds_data.get("status")
            
            print(f"check_balance status (non-cancelable): {check_balance_status}")
            print(f"transfer_funds status (cancelable): {transfer_funds_status}")
            assert check_balance_status == "DISCARDED", f"Expected check_balance to be DISCARDED, got {check_balance_status}"
            assert transfer_funds_status == "CANCELLED", f"Expected transfer_funds to be CANCELLED, got {transfer_funds_status}"
            print("Test 4: PASSED")

    finally:
        pipeline.unregister_playback_client(session_id)
        await pipeline.stop()
        settings.env = orig_env

if __name__ == "__main__":
    asyncio.run(test_integration())
