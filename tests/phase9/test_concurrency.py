import pytest
import asyncio
from services.orchestrator.state_store import save_turn, load_history, clear_session

def test_concurrent_sessions_no_leakage_and_latency_holds():
    async def run_test():
        session_a = "session-a-concurrent"
        session_b = "session-b-concurrent"
        
        # Clear both sessions first to ensure clean state
        clear_session(session_a)
        clear_session(session_b)
        
        # Save turns concurrently
        await asyncio.gather(
            asyncio.to_thread(save_turn, session_a, "1", "user", "Hello from A"),
            asyncio.to_thread(save_turn, session_b, "1", "user", "Hello from B")
        )
        
        # Load history concurrently
        history_a, history_b = await asyncio.gather(
            asyncio.to_thread(load_history, session_a),
            asyncio.to_thread(load_history, session_b)
        )
        
        # Assert absolutely NO cross-session state leakage
        assert len(history_a) == 1
        assert history_a[0]["content"] == "Hello from A"
        
        assert len(history_b) == 1
        assert history_b[0]["content"] == "Hello from B"
        
        # Clear sessions
        clear_session(session_a)
        clear_session(session_b)
        
    asyncio.run(run_test())
