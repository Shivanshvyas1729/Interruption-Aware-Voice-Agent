from enum import StrEnum

class EventNames(StrEnum):
    # ---------------- Phase 0 ----------------
    
    SERVICE_STARTED = "service_started"          # Service has started successfully.

    # ---------------- Phase 1 ----------------
    
    STT_PARTIAL = "stt_partial"                  # Partial speech-to-text transcript received.
    STT_FINAL = "stt_final"                      # Final speech-to-text transcript completed.
    LLM_FIRST_TOKEN = "llm_first_token"          # LLM generated its first response token.
    LLM_COMPLETE = "llm_complete"                # LLM finished generating the response.
    TTS_FIRST_AUDIO = "tts_first_audio"          # TTS started streaming audio.
    TTS_COMPLETE = "tts_complete"                # TTS finished streaming audio.
    TURN_TOTAL_MS = "turn_total_ms"              # Total time taken for one conversation turn.
    STATE_TRANSITION = "state_transition"        # Conversation state changed (e.g., Listening → Thinking).
    ROOM_CREATED = "room_created"                # LiveKit room/session created.
    TRACK_PUBLISHED = "track_published"          # Audio track published to LiveKit.
    TRACK_SUBSCRIBED = "track_subscribed"        # Audio track subscribed/received.

    # ---------------- Phase 3 ----------------
    
    VAD_LOCAL_DUCK = "vad_local_duck"            # User speech detected by Voice Activity Detection (VAD).
    BARGE_IN_DETECTED = "barge_in_detected"      # User interrupted the AI while it was speaking.
    TTS_KILL_SIGNAL_SENT = "tts_kill_signal_sent"# Stop signal sent to TTS.
    TTS_STOPPED = "tts_stopped"                  # TTS stopped speaking.

    # ---------------- Phase 4 ----------------
    
    INTERRUPTION_CLASSIFIED = "interruption_classified"  # Interruption type identified.

    # ---------------- Phase 5 ----------------
    
    INTERRUPTION_RESOLVED = "interruption_resolved"      # Interruption handled (resume, cancel, etc.).

    # ---------------- Phase 6 ----------------
    
    TOOL_CALL_STARTED = "tool_call_started"      # External tool/API execution started.
    TOOL_CALL_INTERRUPTED = "tool_call_interrupted"  # Tool execution interrupted by user.
    TOOL_CALL_COMPLETED = "tool_call_completed"  # Tool execution completed.

    # ---------------- Phase 7 ----------------
    
    LLM_FAILOVER_TRIGGERED = "llm_failover_triggered"  # Switched to backup LLM.
    CACHE_HIT = "cache_hit"                      # Response served from cache.
    CACHE_MISS = "cache_miss"                    # No cached response found.

    # ---------------- Phase 8 ----------------
    
    GUARDRAIL_BLOCKED = "guardrail_blocked"      # Request blocked by safety guardrails.
    RAG_RETRIEVED = "rag_retrieved"              # Context retrieved from RAG/vector database.