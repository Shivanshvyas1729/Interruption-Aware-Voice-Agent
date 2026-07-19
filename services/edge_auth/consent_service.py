from common.logging.logger import get_logger

logger = get_logger("consent-service")

def check_consent(session_id: str, purpose: str = "recording_and_processing") -> bool:
    """Validate user consent for recording/processing.
    
    Stubbed to return True for Phase 1.
    """
    # Deliberately simple stub for Phase 1 (ground rule #6)
    outcome = True
    logger.log(
        event_name="consent_checked",
        session_id=session_id,
        turn_id="system",
        detail={"purpose": purpose, "outcome": "approved", "note": "Phase 1 auto-approval stub"}
    )
    return outcome
