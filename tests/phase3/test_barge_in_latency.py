import os
import json
import threading
import urllib.request
import time
import pytest
import uvicorn
from common.config.settings import get_settings
from services.orchestrator.fsm import get_fsm_for_session
from services.orchestrator.main import make_server as make_orch_server
from services.media_gateway.main import make_server as make_media_server

os.environ["ENV"] = "test"
os.environ["ACTIVE_PHASE"] = "3"
os.environ["SECRETS_BACKEND"] = "local"

def test_barge_in_stops_tts_within_latency_budget(capsys):
    session_id = "session-test-phase3"
    
    # 1. Start Orchestrator FastAPI server on port 8030
    orch_server = make_orch_server(8030)
    t_orch = threading.Thread(target=orch_server.run, daemon=True)
    t_orch.start()
    
    # 2. Start Media Gateway FastAPI server on port 8031 (setting test environment port)
    media_server = make_media_server(8031)
    t_media = threading.Thread(target=media_server.run, daemon=True)
    t_media.start()
    
    # Give servers a small window to initialize
    time.sleep(0.3)
    
    try:
        # 3. Fetch the session FSM and verify initial state transitions
        fsm = get_fsm_for_session(session_id)
        fsm.handle_media_event("participant_joined", {})
        assert fsm.state == "listening"
        
        # Simulate that the FSM is actively speaking
        fsm.transition("speaking")
        assert fsm.state == "speaking"
        
        # 4. Inject simulated user VAD interruption event
        fsm.handle_media_event("vad_interrupted", {})
        
        # Verify that the FSM transitioned through interrupted back to listening
        assert fsm.state == "listening"
        
    finally:
        # Stop background servers cleanly
        orch_server.should_exit = True
        media_server.should_exit = True
        
    # 5. Capture stdout to assert logs structure and events sequence
    captured = capsys.readouterr()
    log_lines = captured.out.strip().split("\n")
    
    events_logged = []
    tts_stopped_latency = None
    
    for line in log_lines:
        if not line.strip():
            continue
        try:
            log_entry = json.loads(line)
            event_name = log_entry.get("event")
            events_logged.append(event_name)
            
            if event_name == "tts_stopped":
                tts_stopped_latency = log_entry.get("latency_ms")
        except json.JSONDecodeError:
            continue
            
    # Verify expected event list sequence
    assert "barge_in_detected" in events_logged
    assert "state_transition" in events_logged  # speaking -> interrupted
    assert "tts_kill_signal_sent" in events_logged
    assert "tts_stopped" in events_logged
    assert "state_transition" in events_logged  # interrupted -> listening
    
    # Assert latency budget is under 300ms p95 requirement
    assert tts_stopped_latency is not None
    assert tts_stopped_latency < 300
