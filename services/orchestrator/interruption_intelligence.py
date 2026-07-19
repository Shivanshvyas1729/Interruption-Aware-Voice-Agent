import time
from common.logging.logger import get_logger
from services.orchestrator.interruption_config import load_interruption_config
from services.orchestrator.interruption_classifier import classify

logger = get_logger("interruption-intelligence")

class InterruptionIntelligence:
    def __init__(self):
        self.config = load_interruption_config()

    def evaluate_interruption(
        self,
        transcript: str,
        stt_confidence: float = 1.0,
        speech_duration_ms: int = 300,
        assistant_speaking_time_ms: int = 1000,
        fsm_state: str = "speaking",
        is_final: bool = True,
        context: dict = None
    ) -> dict:
        """
        Intelligently decides if assistant should continue speaking, stop, or restart.
        
        Returns:
            dict: {
                "decision": "IGNORE_CONTINUE" | "ABORT_ALL" | "CANCEL_AND_RESTART",
                "category": "backchannel" | "stop_cancel" | "correction" | "topic_change" | "clarification" | "noise",
                "confidence": float,
                "reason": str
            }
        """
        start_eval_time = time.time()
        cleaned_text = transcript.strip(".,?! ").lower()
        
        # 1. Configuration Threshold Caching
        thresholds = self.config.get("confidence_thresholds", {})
        timing = self.config.get("timing", {})
        categories = self.config.get("categories", {})
        weights = self.config.get("weights", {})
        
        min_speech_duration = timing.get("min_speech_duration_ms", 200)
        stt_min_conf = thresholds.get("stt_min", 0.5)
        intent_min_conf = thresholds.get("intent_min", 0.6)
        
        # 2. Step 4 Weight Factor Variables
        w_t = weights.get("w_t", 0.4)
        w_d = weights.get("w_d", 0.2)
        w_conf = weights.get("w_conf", 0.2)
        w_overlap = weights.get("w_overlap", 0.2)
        
        # 3. Check for Short Duration Noise (VAD thresholding)
        if speech_duration_ms < min_speech_duration:
            return self._build_result(
                "IGNORE_CONTINUE", "noise", 1.0,
                f"Speech duration ({speech_duration_ms}ms) below minimum threshold ({min_speech_duration}ms)."
            )
            
        # 4. Check for low STT confidence (Noise/Mumbles filtering)
        if stt_confidence < stt_min_conf:
            return self._build_result(
                "IGNORE_CONTINUE", "noise", stt_confidence,
                f"STT confidence ({stt_confidence}) below minimum threshold ({stt_min_conf})."
            )
            
        # 5. Empty transcript check
        if not cleaned_text:
            return self._build_result(
                "IGNORE_CONTINUE", "noise", 1.0,
                "Empty transcript received."
            )
            
        # 6. Fast-path Rule Base Category Lookup
        # Backchannel fast checking
        if cleaned_text in categories.get("backchannel", []):
            return self._build_result(
                "IGNORE_CONTINUE", "backchannel", 1.0,
                "Direct match on backchannel phrase list."
            )
            
        # Stop phrase checking
        for phrase in categories.get("stop_cancel", []):
            if phrase in cleaned_text:
                return self._build_result(
                    "ABORT_ALL", "stop_cancel", 1.0,
                    f"Direct match on stop phrase: '{phrase}'."
                )
                
        # Correction checking
        for phrase in categories.get("correction", []):
            if cleaned_text.startswith(phrase) or phrase in cleaned_text:
                return self._build_result(
                    "CANCEL_AND_RESTART", "correction", 1.0,
                    f"Direct match on correction phrase: '{phrase}'."
                )
                
        # Topic change checking
        for phrase in categories.get("topic_change", []):
            if phrase in cleaned_text:
                return self._build_result(
                    "CANCEL_AND_RESTART", "topic_change", 1.0,
                    f"Direct match on topic change phrase: '{phrase}'."
                )
                
        # Clarification checking
        for phrase in categories.get("clarification", []):
            if phrase in cleaned_text:
                return self._build_result(
                    "CANCEL_AND_RESTART", "clarification", 1.0,
                    f"Direct match on clarification phrase: '{phrase}'."
                )

        # 7. LLM Intent Classification Fallback for Complex Phrases
        # We only call the LLM classifier for final transcripts to avoid API flood on interim segments
        if not is_final:
            return self._build_result(
                "IGNORE_CONTINUE", "noise", 0.5,
                "Interim partial transcript; ignoring until final classification."
            )
            
        classification = classify(transcript)
        intent = classification.get("type", "topic-change")
        intent_conf = classification.get("confidence", 0.8)
        
        # Calculate Weighted Interruption Score
        from common.config.voice_settings import get
        dur_div = get("interruption_weights.dur_score_divider", 1000.0)
        overlap_div = get("interruption_weights.overlap_score_divider", 2000.0)
        dur_score = min(1.0, speech_duration_ms / dur_div)
        overlap_score = min(1.0, assistant_speaking_time_ms / overlap_div)
        
        weighted_score = (w_t * intent_conf) + (w_d * dur_score) + (w_conf * stt_confidence) + (w_overlap * overlap_score)
        
        logger.log(
            event_name="interruption_intelligence_evaluated",
            session_id=context.get("session_id", "system") if context else "system",
            turn_id=context.get("turn_id", "system") if context else "system",
            detail={
                "transcript": transcript,
                "intent": intent,
                "intent_conf": intent_conf,
                "weighted_score": round(weighted_score, 3),
                "threshold": intent_min_conf
            }
        )
        
        if weighted_score < intent_min_conf:
            return self._build_result(
                "IGNORE_CONTINUE", "noise", weighted_score,
                f"Weighted interruption score ({weighted_score:.2f}) below threshold ({intent_min_conf})."
            )
            
        # Map class intent categories to execution decisions
        if intent == "backchannel":
            return self._build_result("IGNORE_CONTINUE", "backchannel", weighted_score, "Classified as backchannel.")
        elif intent == "stop_cancel":
            return self._build_result("ABORT_ALL", "stop_cancel", weighted_score, "Classified as stop/cancel.")
        elif intent == "correction":
            return self._build_result("CANCEL_AND_RESTART", "correction", weighted_score, "Classified as correction.")
        elif intent == "topic-change":
            return self._build_result("CANCEL_AND_RESTART", "topic_change", weighted_score, "Classified as topic change.")
        elif intent == "clarification":
            return self._build_result("CANCEL_AND_RESTART", "clarification", weighted_score, "Classified as clarification.")
            
        return self._build_result("IGNORE_CONTINUE", "noise", weighted_score, "Default fallback ignore.")

    def _build_result(self, decision: str, category: str, confidence: float, reason: str) -> dict:
        return {
            "decision": decision,
            "category": category,
            "confidence": confidence,
            "reason": reason
        }

# Singleton instance
interruption_intel = InterruptionIntelligence()
