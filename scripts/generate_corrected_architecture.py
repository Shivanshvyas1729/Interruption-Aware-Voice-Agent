import json
import os

def generate_corrected():
    source_path = "rules/architecture-1784240202633.json"
    target_path = "docs/architecture/pivot.json"
    
    # Load uncorrected JSON
    with open(source_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    # Corrected edges list
    corrected_edges = [
        # CLIENT ↔ EDGE/AUTH
        {
            "id": "web-to-gw-auth",
            "source": {"nodeId": "web-voice-client", "portId": "out-auth"},
            "target": {"nodeId": "api-gateway", "portId": "in"},
            "type": "http"
        },
        {
            "id": "gw-to-consent",
            "source": {"nodeId": "api-gateway", "portId": "out"},
            "target": {"nodeId": "consent-service", "portId": "in-consent-req"},
            "type": "internal-api"
        },
        {
            "id": "consent-to-token",
            "source": {"nodeId": "consent-service", "portId": "out-consent-res"},
            "target": {"nodeId": "token-service", "portId": "in-auth-req"},
            "type": "internal-api"
        },
        {
            "id": "token-to-gw",
            "source": {"nodeId": "token-service", "portId": "out-auth-res"},
            "target": {"nodeId": "api-gateway", "portId": "left-2"},
            "type": "internal-api"
        },
        {
            "id": "gw-to-web-auth",
            "source": {"nodeId": "api-gateway", "portId": "right-2"},
            "target": {"nodeId": "web-voice-client", "portId": "in-auth"},
            "type": "http"
        },
        {
            "id": "secrets-to-token-keys",
            "source": {"nodeId": "secrets-manager", "portId": "out"},
            "target": {"nodeId": "token-service", "portId": "left-2"},
            "type": "internal-api"
        },
        {
            "id": "gw-to-secrets",
            "source": {"nodeId": "api-gateway", "portId": "right-3"},
            "target": {"nodeId": "secrets-manager", "portId": "in"},
            "type": "internal-api"
        },

        # CLIENT ↔ MEDIA (hot path)
        {
            "id": "web-to-livekit-audio",
            "source": {"nodeId": "web-voice-client", "portId": "out-audio"},
            "target": {"nodeId": "livekit-server", "portId": "in-audio-client"},
            "type": "webrtc"
        },
        {
            "id": "livekit-to-web-audio",
            "source": {"nodeId": "livekit-server", "portId": "out-audio-client"},
            "target": {"nodeId": "web-voice-client", "portId": "in-audio"},
            "type": "webrtc"
        },
        {
            "id": "livekit-to-stt-audio",
            "source": {"nodeId": "livekit-server", "portId": "out-audio-stt"},
            "target": {"nodeId": "deepgram-stt", "portId": "in-audio"},
            "type": "websocket"
        },
        {
            "id": "stt-to-orch-transcript",
            "source": {"nodeId": "deepgram-stt", "portId": "out-transcript"},
            "target": {"nodeId": "orchestrator", "portId": "in-transcript"},
            "type": "websocket"
        },
        {
            "id": "livekit-to-orch-events",
            "source": {"nodeId": "livekit-server", "portId": "out-events"},
            "target": {"nodeId": "orchestrator", "portId": "in-media-events"},
            "type": "websocket"
        },
        {
            "id": "orch-to-tts-text",
            "source": {"nodeId": "orchestrator", "portId": "out-tts-text"},
            "target": {"nodeId": "cartesia-tts", "portId": "in-tts-text"},
            "type": "websocket"
        },
        {
            "id": "orch-to-tts-ctrl-signal",
            "source": {"nodeId": "orchestrator", "portId": "out-tts-ctrl"},
            "target": {"nodeId": "cartesia-tts", "portId": "in-tts-ctrl"},
            "type": "websocket"
        },
        {
            "id": "tts-to-livekit-audio",
            "source": {"nodeId": "cartesia-tts", "portId": "out-audio"},
            "target": {"nodeId": "livekit-server", "portId": "in-audio-tts"},
            "type": "websocket"
        },
        {
            "id": "tts-to-orch-ts",
            "source": {"nodeId": "cartesia-tts", "portId": "out-word-ts"},
            "target": {"nodeId": "orchestrator", "portId": "in-word-ts"},
            "type": "websocket"
        },

        # ORCHESTRATOR ↔ INTELLIGENCE
        {
            "id": "orch-to-guard-req",
            "source": {"nodeId": "orchestrator", "portId": "out-safety-req"},
            "target": {"nodeId": "guardrails-service", "portId": "in-safety-check"},
            "type": "internal-api"
        },
        {
            "id": "guard-to-orch-res",
            "source": {"nodeId": "guardrails-service", "portId": "out-safety-res"},
            "target": {"nodeId": "orchestrator", "portId": "in-safety-res"},
            "type": "internal-api"
        },
        {
            "id": "orch-to-cache-req",
            "source": {"nodeId": "orchestrator", "portId": "out-cache-req"},
            "target": {"nodeId": "llm-semantic-cache", "portId": "in-cache-req"},
            "type": "internal-api"
        },
        {
            "id": "cache-to-orch-res",
            "source": {"nodeId": "llm-semantic-cache", "portId": "out-cache-res"},
            "target": {"nodeId": "orchestrator", "portId": "in-cache-res"},
            "type": "internal-api"
        },
        {
            "id": "orch-to-llm-req",
            "source": {"nodeId": "orchestrator", "portId": "out-llm-req"},
            "target": {"nodeId": "primary-llm", "portId": "in-llm-req"},
            "type": "internal-api"
        },
        {
            "id": "llm-to-orch-stream",
            "source": {"nodeId": "primary-llm", "portId": "out-llm-stream"},
            "target": {"nodeId": "orchestrator", "portId": "in-llm-stream"},
            "type": "internal-api"
        },
        {
            "id": "fallback-to-orch-stream",
            "source": {"nodeId": "fallback-llm", "portId": "out-llm-stream"},
            "target": {"nodeId": "orchestrator", "portId": "in-llm-stream"},
            "type": "internal-api"
        },
        {
            "id": "orch-to-kb-req",
            "source": {"nodeId": "orchestrator", "portId": "out-kb-lookup"},
            "target": {"nodeId": "knowledge-base-memory-db", "portId": "in-kb-req"},
            "type": "internal-api"
        },
        {
            "id": "kb-to-orch-res",
            "source": {"nodeId": "knowledge-base-memory-db", "portId": "out-kb-res"},
            "target": {"nodeId": "orchestrator", "portId": "in-kb-res"},
            "type": "internal-api"
        },
        {
            "id": "orch-to-redis-state",
            "source": {"nodeId": "orchestrator", "portId": "out-state-update"},
            "target": {"nodeId": "app-state-store-db", "portId": "in"},
            "type": "database"
        },
        {
            "id": "redis-to-orch-state",
            "source": {"nodeId": "app-state-store-db", "portId": "out"},
            "target": {"nodeId": "orchestrator", "portId": "in-state-update"},
            "type": "database"
        },
        {
            "id": "orch-to-obs-telemetry",
            "source": {"nodeId": "orchestrator", "portId": "out-telemetry"},
            "target": {"nodeId": "observability-stack", "portId": "in-telemetry"},
            "type": "internal-api"
        },

        # TOOLS & WORKERS
        {
            "id": "redis-to-worker-job",
            "source": {"nodeId": "app-state-store-db", "portId": "out"},
            "target": {"nodeId": "task-execution-service", "portId": "in"},
            "type": "async-event"
        },
        {
            "id": "worker-to-api-req",
            "source": {"nodeId": "task-execution-service", "portId": "out-api-req"},
            "target": {"nodeId": "external-apis-integration", "portId": "in-api"},
            "type": "http"
        },
        {
            "id": "api-to-worker-res",
            "source": {"nodeId": "external-apis-integration", "portId": "out-api"},
            "target": {"nodeId": "task-execution-service", "portId": "in-api-res"},
            "type": "http"
        },
        {
            "id": "worker-to-redis-status",
            "source": {"nodeId": "task-execution-service", "portId": "right-3"},
            "target": {"nodeId": "app-state-store-db", "portId": "left-2"},
            "type": "database"
        }
    ]
    
    # Overwrite edges in data
    data["edges"] = corrected_edges
    
    # Make sure output directory exists
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    
    # Write corrected JSON
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        
    print(f"Successfully generated corrected architecture JSON at: {target_path}")

if __name__ == "__main__":
    generate_corrected()
