import sys
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from services.media_gateway.room_manager import create_room, stop_tts_relay, cleanup_session
from common.logging.logger import get_logger

logger = get_logger("media-gateway")
app = FastAPI(title="Media Gateway Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSControlRequest(BaseModel):
    session_id: str
    action: str

class SessionCleanupRequest(BaseModel):
    session_id: str

@app.post("/tts-control")
async def tts_control(req: TTSControlRequest):
    """Control active audio streaming contexts (e.g. stop relaying on user interruption)."""
    if req.action == "stop":
        stop_tts_relay(req.session_id)
    return {"status": "ok"}

@app.post("/control/cleanup")
async def control_cleanup(req: SessionCleanupRequest):
    """Clean up active session state in the media gateway."""
    cleanup_session(req.session_id)
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

def make_server(port: int = None) -> uvicorn.Server:
    from common.config.voice_settings import get as vc_get
    if port is None:
        port = vc_get("ports.media_gateway", 8001)
    log_level = vc_get("logging.uvicorn_level", "error")
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level=log_level)
    server = uvicorn.Server(config)
    
    logger.log(
        event_name="service_started",
        session_id="system",
        turn_id="system",
        detail={"port": port}
    )
    return server

def run_server(port: int = None) -> None:
    from common.config.voice_settings import get as vc_get
    if port is None:
        port = vc_get("ports.media_gateway", 8001)
    server = make_server(port)
    server.run()

if __name__ == "__main__":
    from common.config.voice_settings import get as vc_get
    port = int(sys.argv[1]) if len(sys.argv) > 1 else vc_get("ports.media_gateway", 8001)
    run_server(port)
