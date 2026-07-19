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
        self.last_llm_latency = 0
        self.last_tts_latency = 0
        try:
            import os
            self.confidence_threshold = float(os.environ.get("INTERRUPTION_CONFIDENCE_THRESHOLD", "0.6"))
        except Exception:
            self.confidence_threshold = 0.6

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
        
        # Check if we were actively interrupted (state is interrupted or speaking)
        is_interrupted_turn = self.state in {"interrupted", "speaking"}
        
        if is_interrupted_turn:
            self.transition("classifying")
            from services.orchestrator.interruption_intelligence import interruption_intel
            
            from common.config.voice_settings import get as vc_get
            speech_dur = vc_get("interruption.min_speech_duration_ms", 300)
            assistant_speaking_time = int((time.time() - self.turn_start_time) * 1000) if self.turn_start_time > 0 else vc_get("interruption.vad_timeout_ms", 1000)
            
            intel_res = interruption_intel.evaluate_interruption(
                transcript=transcript,
                stt_confidence=1.0,
                speech_duration_ms=speech_dur,
                assistant_speaking_time_ms=assistant_speaking_time,
                fsm_state=self.state,
                is_final=True,
                context={"session_id": self.session_id, "turn_id": str(self.turn_id)}
            )
            
            decision = intel_res["decision"]
            category = intel_res["category"]
            confidence = intel_res["confidence"]
            reason = intel_res["reason"]
            
            # Step 7 Structured Telemetry Logging
            logger.log(
                event_name="interruption_decision_logged",
                session_id=self.session_id,
                turn_id=str(self.turn_id),
                detail={
                    "timestamp": time.time(),
                    "transcript": transcript,
                    "category": category,
                    "confidence": confidence,
                    "decision": decision,
                    "reason": reason,
                    "fsm_state": self.state
                }
            )
            
            if decision == "IGNORE_CONTINUE":
                # Filter out backchannel, do NOT stop speaking
                self.transition("speaking")
                return None, None
            elif decision == "ABORT_ALL":
                # Immediately abort everything and return to idle
                from services.orchestrator.cancellation_manager import cancellation_manager
                cancellation_manager.cancel_session(self.session_id, "stop_cancel")
                from services.orchestrator.tts_client import kill as tts_kill
                try:
                    tts_kill(self.session_id)
                except Exception:
                    pass
                self.transition("idle")
                return None, None
            elif decision == "CANCEL_AND_RESTART":
                # Cancel active response and begin the new topic/correction immediately
                from services.orchestrator.cancellation_manager import cancellation_manager
                cancellation_manager.cancel_session(self.session_id, category)
                cancellation_manager.reset_session(self.session_id)
                self.transition("thinking")
        else:
            from services.orchestrator.cancellation_manager import cancellation_manager
            cancellation_manager.reset_session(self.session_id)
            self.transition("thinking")
        
        from services.orchestrator.cancellation_manager import cancellation_manager
        if cancellation_manager.is_cancelled(self.session_id):
            return None, None
            
        # 1. Load history from Redis/State Store
        from services.orchestrator.state_store import load_history, save_turn
        history = load_history(self.session_id)
        
        # 2. Append user's transcript as a new user message
        history.append({"role": "user", "content": transcript})
        
        # Save user turn to state store
        save_turn(self.session_id, str(self.turn_id), "user", transcript)
        
        # 3. Call LLM with the complete history list
        start_llm = time.time()
        reply_text = call_primary(self.session_id, str(self.turn_id), history)
        self.last_llm_latency = int((time.time() - start_llm) * 1000)
        
        if cancellation_manager.is_cancelled(self.session_id):
            return None, None
            
        # 4. Save agent's reply to state store
        save_turn(self.session_id, str(self.turn_id), "assistant", reply_text)
        
        # Thinking -> Speaking
        self.transition("speaking")
        
        # Invoke TTS (Cartesia)
        start_tts = time.time()
        audio_bytes = tts_speak(self.session_id, str(self.turn_id), reply_text)
        self.last_tts_latency = int((time.time() - start_tts) * 1000)
        
        if cancellation_manager.is_cancelled(self.session_id):
            return None, None
            
        # Calculate turnaround metrics
        total_time_ms = int((time.time() - self.turn_start_time) * 1000)
        self.last_total_latency = total_time_ms
        logger.log(
            event_name="turn_total_ms",
            session_id=self.session_id,
            turn_id=str(self.turn_id),
            latency_ms=total_time_ms,
            detail={}
        )
        
        # Speaking -> Listening (waiting for next user turn)
        self.transition("listening")
        return reply_text, audio_bytes

_fsms = {}

def get_fsm_for_session(session_id: str) -> VoiceAgentFSM:
    """Retrieve or create the FSM instance for a session."""
    global _fsms
    if session_id not in _fsms:
        _fsms[session_id] = VoiceAgentFSM(session_id)
    return _fsms[session_id]
