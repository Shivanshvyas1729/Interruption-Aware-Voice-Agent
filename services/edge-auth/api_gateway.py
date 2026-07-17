from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from services.edge_auth.consent_service import check_consent
from services.edge_auth.token_service import issue_token
from common.logging.logger import get_logger

logger = get_logger("api-gateway")
app = FastAPI(title="API Gateway")

class AuthRequest(BaseModel):
    session_id: str
    room_name: str

@app.post("/auth")
async def auth_route(req: AuthRequest):
    """Receive authentication requests, check consent, issue room token."""
    logger.log(
        event_name="auth_request_received",
        session_id=req.session_id,
        turn_id="system",
        detail={"room_name": req.room_name}
    )
    
    # Check user consent
    consent_approved = check_consent(req.session_id)
    if not consent_approved:
        logger.log(
            event_name="auth_request_routed",
            session_id=req.session_id,
            turn_id="system",
            detail={"outcome": "consent_denied"}
        )
        raise HTTPException(status_code=403, detail="Consent denied")
        
    # Issue LiveKit room token
    try:
        token = issue_token(req.session_id, req.room_name)
        logger.log(
            event_name="auth_request_routed",
            session_id=req.session_id,
            turn_id="system",
            detail={"outcome": "success"}
        )
        return {"token": token}
    except Exception as e:
        logger.log(
            event_name="auth_request_routed",
            session_id=req.session_id,
            turn_id="system",
            detail={"outcome": f"failed: {str(e)}"}
        )
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
