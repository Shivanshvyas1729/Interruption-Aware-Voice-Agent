import json
import os
import threading
import urllib.request
import sys
import importlib.util
import pytest
import time

# Ensure environments are configured for test duration
os.environ["ACTIVE_PHASE"] = "0"
os.environ["SECRETS_BACKEND"] = "local"

def import_service_main(service_name: str):
    """Dynamically import main.py from services."""
    underscore_name = service_name.replace('-', '_')
    spec = importlib.util.spec_from_file_location(
        f"services.{underscore_name}.main",
        f"services/{underscore_name}/main.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module.__name__] = module
    spec.loader.exec_module(module)
    return module

def test_all_services_healthy_and_log_startup(capsys):
    from common.config.voice_settings import get as vc_get
    orch_main = import_service_main("orchestrator")
    media_main = import_service_main("media-gateway")
    worker_main = import_service_main("task-worker")
    
    orch_port = vc_get("ports.orchestrator", 8000)
    media_port = vc_get("ports.media_gateway", 8001)
    worker_port = vc_get("ports.task_worker", 8002)
    orch_server = orch_main.make_server(orch_port)
    media_server = media_main.make_server(media_port)
    worker_server = worker_main.make_server(worker_port)
    
    # Start servers in daemon threads
    servers = [orch_server, media_server, worker_server]
    threads = []
    for server in servers:
        target = server.serve_forever if hasattr(server, "serve_forever") else server.run
        t = threading.Thread(target=target, daemon=True)
        t.start()
        threads.append(t)
        
    from common.config.voice_settings import get as vc_get
    try:
        time.sleep(0.3)
        test_ports = [
            (vc_get("ports.orchestrator", 8000), "orchestrator"),
            (vc_get("ports.media_gateway", 8001), "media-gateway"),
            (vc_get("ports.task_worker", 8002), "task-worker"),
        ]
        for port, name in test_ports:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                assert response.status == 200
                data = json.loads(response.read().decode("utf-8"))
                assert data["status"] == "healthy"
    finally:
        # Shutdown servers cleanly
        for server in servers:
            if hasattr(server, "server_close"):
                try:
                    server.shutdown()
                    server.server_close()
                except Exception:
                    pass
            else:
                server.should_exit = True
            
    # Capture written logs
    captured = capsys.readouterr()
    log_lines = captured.out.strip().split("\n")
    
    events_found = {}
    for line in log_lines:
        if not line.strip():
            continue
        try:
            log_entry = json.loads(line)
            if log_entry.get("event") == "service_started":
                comp = log_entry.get("component")
                events_found[comp] = log_entry
        except json.JSONDecodeError:
            continue
            
    assert "orchestrator" in events_found, f"orchestrator logs not found. Output: {captured.out}"
    assert "media-gateway" in events_found, f"media-gateway logs not found. Output: {captured.out}"
    assert "task-worker" in events_found, f"task-worker logs not found. Output: {captured.out}"
    
    # Verify log schema
    for comp, entry in events_found.items():
        assert "ts" in entry
        assert "session_id" in entry
        assert "turn_id" in entry
        assert "phase" in entry
        assert entry["phase"] == "0"
        assert entry["component"] == comp
        assert entry["event"] == "service_started"
        assert "detail" in entry
        assert isinstance(entry["detail"], dict)

def test_secret_scrubbing(capsys):
    from common.logging.logger import get_logger
    
    # Set dummy credentials to scrub
    os.environ["DEEPGRAM_API_KEY"] = "super_secret_dg_key_123"
    
    logger = get_logger("test-scrubber")
    logger.log("stt_partial", "session-x", "turn-y",
               key_param="super_secret_dg_key_123",
               some_secret="confidential_data",
               safe_param="hello")
    
    captured = capsys.readouterr()
    log_entry = json.loads(captured.out.strip())
    
    # Assert secret values are scrubbed
    assert log_entry["detail"]["key_param"] == "[SCRUBBED]"
    assert log_entry["detail"]["some_secret"] == "[SCRUBBED]"
    assert log_entry["detail"]["safe_param"] == "hello"

def test_architecture_validation_passes():
    import scripts.validate_architecture as val
    arch = val.load_architecture("docs/architecture/pivot.json")
    violations = val.validate(arch)
    assert len(violations) == 0, f"Corrected architecture has validation violations: {violations}"
