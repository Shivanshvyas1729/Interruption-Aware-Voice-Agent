import sys
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from services.orchestrator.stt_client import handle_transcript
from services.orchestrator.fsm import get_fsm_for_session
from common.logging.logger import get_logger

logger = get_logger("orchestrator")
app = FastAPI(title="Orchestrator Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class TranscriptRequest(BaseModel):
    session_id: str
    text: str
    is_final: bool
    latency_ms: int = 0

class MediaEventRequest(BaseModel):
    session_id: str
    kind: str
    ts: float
    detail: dict = {}

@app.post("/transcript")
async def transcript_route(req: TranscriptRequest):
    """Receive transcript segments from media STT wrapper and route to handler."""
    handle_transcript(req.session_id, req.text, req.is_final, req.latency_ms)
    return {"status": "ok"}

@app.post("/media-events")
async def media_events_route(req: MediaEventRequest):
    """Receive event payloads from media gateway and route to session FSM."""
    fsm = get_fsm_for_session(req.session_id)
    fsm.handle_media_event(req.kind, req.detail)
    return {"status": "ok"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

def make_server(port: int = None) -> uvicorn.Server:
    from common.config.voice_settings import get as vc_get
    if port is None:
        port = vc_get("ports.orchestrator", 8000)
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
        port = vc_get("ports.orchestrator", 8000)
    server = make_server(port)
    server.run()

if __name__ == "__main__":
    from common.config.voice_settings import get as vc_get
    port = int(sys.argv[1]) if len(sys.argv) > 1 else vc_get("ports.orchestrator", 8000)
    run_server(port)
