from enum import StrEnum

class EventNames(StrEnum):
    # Phase 0
    SERVICE_STARTED = "service_started"
    
    # Phase 1
    STT_PARTIAL = "stt_partial"
    STT_FINAL = "stt_final"
    LLM_FIRST_TOKEN = "llm_first_token"
    LLM_COMPLETE = "llm_complete"
    TTS_FIRST_AUDIO = "tts_first_audio"
    TTS_COMPLETE = "tts_complete"
    TURN_TOTAL_MS = "turn_total_ms"
    STATE_TRANSITION = "state_transition"
    ROOM_CREATED = "room_created"
    TRACK_PUBLISHED = "track_published"
    TRACK_SUBSCRIBED = "track_subscribed"
    
    # Phase 3
    VAD_LOCAL_DUCK = "vad_local_duck"
    BARGE_IN_DETECTED = "barge_in_detected"
    TTS_KILL_SIGNAL_SENT = "tts_kill_signal_sent"
    TTS_STOPPED = "tts_stopped"
    
    # Phase 4
    INTERRUPTION_CLASSIFIED = "interruption_classified"
    
    # Phase 5
    INTERRUPTION_RESOLVED = "interruption_resolved"
    
    # Phase 6
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_INTERRUPTED = "tool_call_interrupted"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    
    # Phase 7
    LLM_FAILOVER_TRIGGERED = "llm_failover_triggered"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    
    # Phase 8
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    RAG_RETRIEVED = "rag_retrieved"
