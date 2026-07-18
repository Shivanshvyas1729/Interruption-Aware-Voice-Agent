import sys
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from services.media_gateway.room_manager import create_room, stop_tts_relay
from common.logging.logger import get_logger

logger = get_logger("media-gateway")
app = FastAPI(title="Media Gateway Service")

class TTSControlRequest(BaseModel):
    session_id: str
    action: str

@app.post("/tts-control")
async def tts_control(req: TTSControlRequest):
    """Control active audio streaming contexts (e.g. stop relaying on user interruption)."""
    if req.action == "stop":
        stop_tts_relay(req.session_id)
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

def make_server(port: int = 8001) -> uvicorn.Server:
    """Create a Uvicorn server instance programmatically for testing."""
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="error")
    server = uvicorn.Server(config)
    
    logger.log(
        event_name="service_started",
        session_id="system",
        turn_id="system",
        detail={"port": port}
    )
    return server

def run_server(port: int = 8001) -> None:
    server = make_server(port)
    server.run()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    run_server(port)
