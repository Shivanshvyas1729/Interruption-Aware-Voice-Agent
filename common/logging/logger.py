import os
import sys
import json
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Phase mapping for events
EVENT_PHASES: Dict[str, str] = {
    # Phase 0
    "service_started": "0",
    "service_stopped": "0",
    "secret_accessed": "0",
    
    # Phase 1
    "stt_partial": "1",
    "stt_final": "1",
    "llm_first_token": "1",
    "llm_complete": "1",
    "tts_first_audio": "1",
    "tts_complete": "1",
    "turn_total_ms": "1",
    "state_transition": "1",
    "room_created": "1",
    "track_published": "1",
    "track_subscribed": "1",
    
    # Phase 3
    "vad_local_duck": "3",
    "barge_in_detected": "3",
    "tts_kill_signal_sent": "3",
    "tts_stopped": "3",
    
    # Phase 4
    "interruption_classified": "4",
    
    # Phase 5
    "interruption_resolved": "5",
    
    # Phase 6
    "tool_call_started": "6",
    "tool_call_interrupted": "6",
    "tool_call_completed": "6",
    
    # Phase 7
    "llm_failover_triggered": "7",
    "cache_hit": "7",
    "cache_miss": "7",
    
    # Phase 8
    "guardrail_blocked": "8",
    "rag_retrieved": "8"
}

def get_secret_values() -> set[str]:
    """Retrieve secret values from environment variables to scrub them."""
    secrets = set()
    for k, v in os.environ.items():
        k_upper = k.upper()
        if k_upper.endswith("_API_KEY") or k_upper.endswith("_SECRET") or "PASSWORD" in k_upper or "TOKEN" in k_upper:
            if v and len(v.strip()) > 3:  # Avoid scrubbing trivial values
                secrets.add(v.strip())
    return secrets

def scrub_val(val: Any, secret_values: set[str]) -> Any:
    """Scrub raw secret values recursively."""
    if isinstance(val, str):
        cleaned = val
        for sec in secret_values:
            if sec in cleaned:
                cleaned = cleaned.replace(sec, "[SCRUBBED]")
        return cleaned
    elif isinstance(val, dict):
        return scrub_dict(val, secret_values)
    elif isinstance(val, list):
        return [scrub_val(item, secret_values) for item in val]
    return val

def scrub_dict(d: Dict[str, Any], secret_values: set[str]) -> Dict[str, Any]:
    """Scrub dictionary keys and values recursively."""
    scrubbed = {}
    for k, v in d.items():
        k_lower = k.lower()
        if any(term in k_lower for term in ["api_key", "secret", "password", "token"]):
            scrubbed[k] = "[SCRUBBED]"
        else:
            scrubbed[k] = scrub_val(v, secret_values)
    return scrubbed

class ComponentLogger:
    """A logger bound to a specific component."""
    def __init__(self, component: str):
        self.component = component

    def log(self, event_name: str, session_id: str, turn_id: str, latency_ms: Optional[int] = None, **detail: Any) -> None:
        """Emit one structured JSON log line to stdout."""
        secret_values = get_secret_values()
        scrubbed_detail = scrub_dict(detail, secret_values)
        
        phase = EVENT_PHASES.get(event_name, "0")
        
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "turn_id": turn_id,
            "phase": phase,
            "component": self.component,
            "event": event_name,
            "latency_ms": latency_ms,
            "detail": scrubbed_detail
        }
        
        sys.stdout.write(json.dumps(record) + "\n")
        sys.stdout.flush()

    def log_service_start(self, service_name: str, **detail: Any) -> None:
        """Log service startup."""
        self.log("service_started", "system", "system", detail={"service": service_name, **detail})

    def log_service_stop(self, service_name: str, **detail: Any) -> None:
        """Log service shutdown."""
        self.log("service_stopped", "system", "system", detail={"service": service_name, **detail})

    def log_error(self, event_name: str, session_id: str, turn_id: str, error: Exception, **detail: Any) -> None:
        """Log an error with full traceback."""
        self.log(event_name, session_id, turn_id, detail={
            **detail,
            "error": str(error),
            "error_type": type(error).__name__,
            "traceback": traceback.format_exc()
        })

    def log_exception(self, event_name: str, session_id: str, turn_id: str, **detail: Any) -> None:
        """Log an exception with full traceback (alias for log_error)."""
        self.log_error(event_name, session_id, turn_id, Exception("Exception logged"), **detail)

def get_logger(component: str) -> ComponentLogger:
    """Retrieve a component-bound logger."""
    return ComponentLogger(component)
