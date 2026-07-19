import os
import json
import threading
import urllib.request
import time
import pytest
from services.orchestrator.fsm import get_fsm_for_session, _fsms
from services.orchestrator.state_store import load_history, clear_session
from services.orchestrator.main import make_server as make_orch_server

os.environ["ENV"] = "test"
os.environ["ACTIVE_PHASE"] = "2"
os.environ["SECRETS_BACKEND"] = "local"

def test_conversation_state_persists_across_turns_and_restart():
    from common.config.voice_settings import get as vc_get
    session_id = "session-test-phase2"
    
    clear_session(session_id)
    if session_id in _fsms:
        del _fsms[session_id]
        
    orch_port = vc_get("ports.test_single_orchestrator", 8020)
    orch_server = make_orch_server(orch_port)
    t = threading.Thread(target=orch_server.run, daemon=True)
    t.start()
    
    # Give server a small window to bind socket
    time.sleep(0.3)
    
    try:
        # 3. Retrieve FSM and verify initial state is idle
        fsm = get_fsm_for_session(session_id)
        assert fsm.state == "idle"
        
        # Simulate room participant join
        fsm.handle_media_event("participant_joined", {})
        assert fsm.state == "listening"
        
        # --- Turn 1 ---
        # User asks: "What is Mars?"
        fsm.receive_transcript("What is Mars?")
        
        # Assert history is populated
        history1 = load_history(session_id)
        assert len(history1) == 2
        assert history1[0]["role"] == "user"
        assert "Mars" in history1[0]["content"]
        assert history1[1]["role"] == "assistant"
        assert "fourth planet" in history1[1]["content"]
        
        # --- SIMULATE PROCESS RESTART ---
        # Clear the in-memory cache of FSM instances to simulate orchestrator crash recovery
        if session_id in _fsms:
            del _fsms[session_id]
            
        # Re-fetch FSM (this creates a clean FSM instance with no internal turn count)
        fsm_restarted = get_fsm_for_session(session_id)
        fsm_restarted.handle_media_event("participant_joined", {})
        
        # --- Turn 2 ---
        # User asks: "How far is it?" (referencing "it" -> Mars)
        fsm_restarted.receive_transcript("How far is it?")
        
        # History should now contain Turn 1 (user/assistant) + Turn 2 (user/assistant)
        history2 = load_history(session_id)
        assert len(history2) == 4
        assert "kilometers" in history2[3]["content"]  # Proves "it" resolved to Mars from history
        
        # --- Turn 3 ---
        fsm_restarted.receive_transcript("Thank you")
        history3 = load_history(session_id)
        assert len(history3) == 6
        assert "welcome" in history3[5]["content"].lower()
        
    finally:
        # Shutdown orchestrator server
        orch_server.should_exit = True
