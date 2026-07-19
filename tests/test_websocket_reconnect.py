import pytest
from fastapi.testclient import TestClient
from services.edge_auth.api_gateway import app
from services.edge_auth.telemetry_bus import telemetry_bus

def test_websocket_telemetry_reconnect():
    client = TestClient(app)
    
    # 1. First connection
    with client.websocket_connect("/ws/telemetry") as websocket:
        # Push a test event
        telemetry_bus.push("test_event_1", {"data": "first"}, "session-1", "turn-1")
        
        # We should be able to receive it
        data = websocket.receive_json()
        # Look for our event in the stream (using 'type' as key)
        while data.get("type") != "test_event_1":
            data = websocket.receive_json()
        assert data["type"] == "test_event_1"
        assert data["data"]["data"] == "first"
        
    # Connection is closed here (simulating client disconnection)
    
    # 2. Reconnect
    with client.websocket_connect("/ws/telemetry") as websocket:
        # Push another event
        telemetry_bus.push("test_event_2", {"data": "second"}, "session-1", "turn-2")
        
        data = websocket.receive_json()
        while data.get("type") != "test_event_2":
            data = websocket.receive_json()
        assert data["type"] == "test_event_2"
        assert data["data"]["data"] == "second"
