from common.logging.logger import get_logger
from services.orchestrator.llm_client import call_primary
from services.orchestrator.tts_client import speak as tts_speak
import time

logger = get_logger("orchestrator")

class VoiceAgentFSM:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = "idle"
        self.turn_id = 0
        self.turn_start_time = 0.0

    def transition(self, target_state: str):
        """Transition FSM to target_state and log state_transition."""
        old_state = self.state
        self.state = target_state
        logger.log(
            event_name="state_transition",
            session_id=self.session_id,
            turn_id=str(self.turn_id),
            detail={"from": old_state, "to": target_state}
        )

    def handle_media_event(self, kind: str, detail: dict):
        """React to room-level participant and audio status events."""
        if kind == "participant_joined":
            if self.state == "idle":
                self.transition("listening")
                
        # Forward event to the barge-in detector (Phase 3)
        from services.orchestrator.barge_in import on_media_event
        on_media_event(self.session_id, kind, detail)

    def receive_transcript(self, transcript: str):
        """Main turn-processing loop triggered by STT transcripts."""
        self.turn_id += 1
        self.turn_start_time = time.time()
        
        # Idle/Listening -> Thinking
        self.transition("thinking")
        
        # 1. Load history from Redis/State Store
        from services.orchestrator.state_store import load_history, save_turn
        history = load_history(self.session_id)
        
        # 2. Append user's transcript as a new user message
        history.append({"role": "user", "content": transcript})
        
        # Save user turn to state store
        save_turn(self.session_id, str(self.turn_id), "user", transcript)
        
        # 3. Call LLM with the complete history list
        reply_text = call_primary(self.session_id, str(self.turn_id), history)
        
        # 4. Save agent's reply to state store
        save_turn(self.session_id, str(self.turn_id), "assistant", reply_text)
        
        # Thinking -> Speaking
        self.transition("speaking")
        
        # Invoke TTS (Cartesia)
        audio_bytes = tts_speak(self.session_id, str(self.turn_id), reply_text)
        
        # Calculate turnaround metrics
        total_time_ms = int((time.time() - self.turn_start_time) * 1000)
        logger.log(
            event_name="turn_total_ms",
            session_id=self.session_id,
            turn_id=str(self.turn_id),
            latency_ms=total_time_ms,
            detail={}
        )
        
        # Speaking -> Listening (waiting for next user turn)
        self.transition("listening")

_fsms = {}

def get_fsm_for_session(session_id: str) -> VoiceAgentFSM:
    """Retrieve or create the FSM instance for a session."""
    global _fsms
    if session_id not in _fsms:
        _fsms[session_id] = VoiceAgentFSM(session_id)
    return _fsms[session_id]
