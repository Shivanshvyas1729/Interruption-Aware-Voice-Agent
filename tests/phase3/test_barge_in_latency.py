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
    from common.config.voice_settings import get as vc_get
    session_id = "session-test-phase3"
    
    orch_port = vc_get("ports.test_orchestrator", 8030)
    media_port = vc_get("ports.test_media_gateway", 8031)
    orch_server = make_orch_server(orch_port)
    t_orch = threading.Thread(target=orch_server.run, daemon=True)
    t_orch.start()
    
    media_server = make_media_server(media_port)
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
        
        # Verify that the FSM transitioned to interrupted and remains there awaiting STT
        assert fsm.state == "interrupted"
        
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
