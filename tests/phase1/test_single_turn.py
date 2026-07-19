import json
import os
import threading
import urllib.request
import time
import pytest
import uvicorn
from common.config.settings import get_settings
from services.orchestrator.fsm import get_fsm_for_session
from services.orchestrator.main import make_server as make_orch_server
from services.edge_auth.api_gateway import app as gateway_app
from services.orchestrator.stt_client import transcribe_audio_file

# Set test configurations
os.environ["ENV"] = "test"
os.environ["ACTIVE_PHASE"] = "1"
os.environ["SECRETS_BACKEND"] = "local"

def test_single_turn_end_to_end_from_fixture(capsys):
    from common.config.voice_settings import get as vc_get
    session_id = "session-test-phase1"
    room_name = "room-test-phase1"
    
    orch_port = vc_get("ports.test_single_orchestrator", 8010)
    gw_port = vc_get("ports.test_api_gateway", 8013)
    
    orch_server = make_orch_server(orch_port)
    t_orch = threading.Thread(target=orch_server.run, daemon=True)
    t_orch.start()
    
    config = uvicorn.Config(gateway_app, host="0.0.0.0", port=gw_port, log_level=vc_get("logging.uvicorn_level", "error"))
    gw_server = uvicorn.Server(config)
    t_gw = threading.Thread(target=gw_server.run, daemon=True)
    t_gw.start()
    
    # Give servers a small window to initialize
    time.sleep(0.5)
    
    try:
        auth_data = json.dumps({"session_id": session_id, "room_name": room_name}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{gw_port}/auth",
            data=auth_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=3) as res:
            assert res.status == 200
            token_res = json.loads(res.read().decode("utf-8"))
            assert "token" in token_res
            assert len(token_res["token"]) > 10
            
        # 4. Fetch the session FSM and verify initial state transitions
        fsm = get_fsm_for_session(session_id)
        assert fsm.state == "idle"
        
        # Simulate room join event
        fsm.handle_media_event("participant_joined", {})
        assert fsm.state == "listening"
        
        # 5. Execute audio transcription from WAV fixture (triggers transcription -> LLM -> TTS loop)
        wav_path = "tests/phase1/fixtures/weather.wav"
        transcript = transcribe_audio_file(session_id, wav_path)
        assert transcript == "What's the weather like on Mars?"
        
        # After completing the turn, FSM should transition back to listening for the next turn
        assert fsm.state == "listening"
        
    finally:
        # Stop background servers cleanly
        orch_server.should_exit = True
        gw_server.should_exit = True
        
    # 6. Capture stdout to assert logs structure and events sequence
    captured = capsys.readouterr()
    log_lines = captured.out.strip().split("\n")
    
    events_logged = []
    for line in log_lines:
        if not line.strip():
            continue
        try:
            log_entry = json.loads(line)
            events_logged.append(log_entry.get("event"))
        except json.JSONDecodeError:
            continue
            
    # Assert telemetry flow matches expectations
    assert "state_transition" in events_logged
    assert "stt_final" in events_logged
    assert "llm_first_token" in events_logged
    assert "llm_complete" in events_logged
    assert "tts_first_audio" in events_logged
    assert "tts_complete" in events_logged
    assert "turn_total_ms" in events_logged
