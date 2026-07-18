import time
from services.orchestrator.tts_client import kill as tts_kill
from services.orchestrator.fsm import get_fsm_for_session
from common.logging.logger import get_logger

logger = get_logger("barge-in")

def on_media_event(session_id: str, event_kind: str, detail: dict = None):
    """Watches for VAD user speech alerts to detect interruptions while agent is speaking."""
    fsm = get_fsm_for_session(session_id)
    
    # In Phase 3, any user speech start during active speaking triggers barge-in
    if event_kind in {"user_speech_start", "user_speech_sustained", "vad_interrupted"}:
        if fsm.state == "speaking":
            trigger_kill(session_id)

def trigger_kill(session_id: str):
    """Fires TTS kill signals, transitions FSM, and tracks latency."""
    start_time = time.time()
    fsm = get_fsm_for_session(session_id)
    
    # 1. Log barge_in_detected
    logger.log(
        event_name="barge_in_detected",
        session_id=session_id,
        turn_id=str(fsm.turn_id),
        detail={"msg": "User interrupted agent speech"}
    )
    
    # 2. Transition FSM to interrupted
    fsm.transition("interrupted")
    
    # 3. Call tts_client.kill() to send kill signal server-side
    tts_kill(session_id)
    
    # Calculate stop latency
    stop_latency = int((time.time() - start_time) * 1000)
    
    # Transition back to listening (idle/ready for new STT input)
    fsm.transition("listening")
