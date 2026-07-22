# Production-Grade Latency & Architectural Remediation Plan (v2.0)

**Document Status**: Final Architecture Sign-Off Specification  
**Target Benchmark**: Sub-250ms TTS Synthesis, Sub-1200ms Total Pipeline Latency at 5,000+ Concurrent Sessions  
**Target Audience**: Principal Systems Architects, Core Infrastructure Team, SRE Lead  

---

## Executive Overview
This document specifies the updated production-grade architectural remediation plan for the real-time voice agent pipeline. It preserves all implemented core fixes (thread synchronization, in-flight connection guards, idle reapers, session-scoped continuation, and HTTP connection pooling) and expands the system design with principal-engineer-level production safeguards: connection state machines, dead connection heartbeat detection, backpressure & load shedding strategies, capacity scaling models (up to 10,000 sessions), chaos testing suites, and deployment rollout gates.

---

## 1. Connection State Machine

Every TTS WebSocket connection transitions through a strictly defined state machine managed by `TTSWorker`:

```
   [NEW] ---> [PREWARMING] ---> [READY] ---> [ACTIVE]
     |              |            |            |
     |              v            v            |
     +-----------> [FAILED] <----+------------+
                     ^           |            |
                     |           v            v
               [RECONNECTING] <----+------- [IDLE]
                     |                        |
                     v                        v
                  [CLOSED] <------------------+
```

### State Definitions & Ownership

| State | Entry Condition | Exit Condition | Owner | Cleanup Action |
| :--- | :--- | :--- | :--- | :--- |
| **NEW** | Session initialized | Connection request dispatched | `TTSWorker` | Remove session key |
| **PREWARMING** | Gateway `/stream` connected | WS handshake complete or error | `TTSWorker` | Set failure event, release wait locks |
| **READY** | WS handshake & context open | Sentence push request received | `TTSWorker` | Register in `_ws_sessions` |
| **ACTIVE** | `ws_ctx.push()` called | Audio frame streaming complete | `TTSWorker` | Update `_last_accessed` timestamp |
| **IDLE** | Audio stream `done` event | New turn sentence OR idle timeout | `TTSWorker` | Reset turn state, retain socket |
| **RECONNECTING** | Socket error / ping timeout | Successful reconnect OR max retries | `TTSWorker` | Flush pending frame buffer |
| **FAILED** | Max retries exceeded / 4xx error | Fallback to REST or terminal error | `TTSWorker` | Pop session, release socket handles |
| **CLOSED** | Session disconnect / Reaper (60s) | Process exit / explicit destroy | `TTSWorker` | Send WS close frame, clear buffers |

---

## 2. Heartbeat & Dead Connection Detection

To detect half-open TCP connections (e.g., silent Wi-Fi drop or cloud NAT gateway timeout) without blocking audio streaming:

- **Ping Interval**: Every **15 seconds** during `IDLE` state.
- **Pong Timeout**: **5.0 seconds** max wait for pong frames from Cartesia WS.
- **Half-Open Detection**: If a ping frame is unacknowledged after 5 seconds, or if TCP socket read times out during `ACTIVE` streaming, the socket is immediately classified as `FAILED`.
- **Automatic Cleanup**: The dead socket is popped from `_ws_sessions`, closed asynchronously to free system file descriptors, and marked for clean reconnection on the next sentence push.

---

## 3. Reconnection Policy & Circuit Breaker

To prevent reconnect storms during Cartesia API degradation or network instability:

- **Max Reconnect Attempts**: **3 attempts** per session before falling back to REST.
- **Exponential Backoff with Jitter**:
  $$\text{Delay} = \min\left(\text{MaxDelay}, \text{BaseDelay} \times 2^{\text{attempt}}\right) + \text{Uniform}(0, \text{Jitter})$$
  - `BaseDelay`: 100ms
  - `MaxDelay`: 2000ms
  - `Jitter`: Random 0–50ms
- **Circuit Breaker Integration**:
  - **Threshold**: If **>15% of connection attempts** across all sessions fail within a 30-second window, the global TTS Circuit Breaker flips to `OPEN`.
  - **Open Behavior**: Automatically routes all TTS requests to REST fallback or mock without attempting WS handshakes for 15 seconds.
  - **Half-Open Probe**: After 15 seconds, allows 5 probe connections to evaluate upstream health before resetting to `CLOSED`.

---

## 4. Resource Ownership Matrix

Clear resource lifecycle boundary responsibilities prevent double-cleanup and memory leaks:

| Resource | Creator | Primary Owner | Cleanup Responsibility | Destruction Trigger |
| :--- | :--- | :--- | :--- | :--- |
| **Cartesia Client** | `get_cartesia_client()` | Global Module | Process Shutdown | App SIGTERM |
| **WebSocket Connection** | `open_ws_context()` | `TTSWorker` | `TTSWorker.cleanup_session_ws()` | Session disconnect / Idle reaper |
| **Cartesia Context (`ctx`)** | `open_ws_context()` | `TTSWorker` | `TTSWorker` (tied to WS) | WS teardown / failure reset |
| **HTTP `requests.Session`** | `get_requests_session()`| Global Module | Process Shutdown | App SIGTERM |
| **Playback Queue** | `api_gateway.py` | `PlaybackWorker` | `PlaybackWorker.unregister_client()` | WebSocket stream disconnect |
| **Session Lock / State** | `TTSWorker` | `TTSWorker` | `TTSWorker.cleanup_session_ws()` | Session unregistration |
| **Cancel Token** | `cancel_token.py` | Global Registry | `cleanup_session()` | Gateway disconnect |
| **Telemetry Bus** | `api_gateway.py` | Global Registry | Telemetry Worker | Process Exit |

---

## 5. Connection & Capacity Limits

| Parameter | Limit | Enforcement Point | Action on Breach |
| :--- | :--- | :--- | :--- |
| **Max WS Per Session** | 1 | `TTSWorker._get_or_create_ws` | Reject second connect, reuse active |
| **Idle Socket Timeout** | 60 seconds | `_idle_reaper_loop()` | Close WS, move to `CLOSED` state |
| **Max Connection Lifetime**| 30 minutes | `_idle_reaper_loop()` | Re-connect on next turn |
| **Max Reconnect Attempts** | 3 per turn | `TTSWorker._tts_sync` | Degrade to REST fallback |
| **HTTP Pool Size** | 200 connections | `urllib3.HTTPAdapter` | Queue until connection freed |

---

## 6. Backpressure & Queue Management

When audio producers generate chunks faster than the client network socket can consume:

```
[TTSWorker] ---> (AudioChunk) ---> [Playback Queue (max 100)] ---> [WebSocket Wire]
                                            |
                                  (Queue Full > 100)
                                            v
                                  [Backpressure Action]
```

- **Playback Queue Cap**: `websocket_queue_size: 100` (~3.5 seconds of audio buffer).
- **Producer Behavior**:
  - If Playback Queue reaches **80% capacity (80 chunks)**: Telemetry logs `playback_queue_high_watermark`.
  - If Playback Queue is **FULL (100 chunks)**: Block TTS worker put with a **500ms timeout**.
  - If timeout expires: Drop oldest unplayed non-terminal chunk and push `playback_chunk_dropped` metric.
- **Interruption Behavior**: On user interrupt signal, immediately clear all pending items from Playback Queue, reset turn state, and emit terminal `stop_audio` frame.

---

## 7. Load Shedding & Degradation Hierarchy

Under extreme system stress or upstream outages, the system sheds load systematically:

1. **Level 1 (Normal Operation)**: Pre-warmed persistent WebSockets with session context reuse (<250ms latency).
2. **Level 2 (Upstream WS Degradation)**: Degrade failed session to REST streaming API (`speak_stream`) while keeping other sessions on WS (~400–600ms latency).
3. **Level 3 (Thread Pool Saturation >90%)**: Bypass non-essential telemetry logging and disable audio chunk timestamp tracking to free thread CPU.
4. **Level 4 (Global Upstream Outage / Circuit Breaker OPEN)**: Instantly fail fast or return mock audio for non-critical turns, rejecting new WS pre-warm requests at the API Gateway with HTTP 503 / `retry_after: 5`.

---

## 8. Capacity Planning & Resource Scale Models

Est. resource consumption for concurrent active user sessions:

| Concurrent Sessions | Active WebSockets | Thread Pool Workers | RAM Usage | Max Network Throughput |
| :--- | :--- | :--- | :--- | :--- |
| **100** | 100 | 20 | ~150 MB | 4.8 Mbps |
| **1,000** | 1,000 | 100 | ~850 MB | 48.0 Mbps |
| **5,000** | 5,000 | 200 | ~3.8 GB | 240.0 Mbps |
| **10,000** | 10,000 (Multi-node) | 400 (Distributed) | ~7.2 GB | 480.0 Mbps |

*Architectural Recommendation*: Node sizing should cap single-instance concurrency at **2,500 active sessions** to preserve thread context-switching efficiency. Beyond 2,500 sessions, scale horizontally behind an L4/L7 load balancer.

---

## 9. Comprehensive Testing & Chaos Strategy

### 1. Unit Tests
- `test_ws_connection_reuse()`: Verify 5 sequential turns execute on 1 single WebSocket handle.
- `test_thread_safety_concurrent_prewarm()`: Simulate 50 concurrent threads accessing `_get_or_create_ws()` simultaneously.
- `test_idle_socket_reaper()`: Fast-forward idle timestamp and verify reaper closes socket after 60s.

### 2. Integration Tests
- `test_interruption_mid_stream()`: Verify active audio streaming cancels immediately without corrupting subsequent turns.
- `test_session_cleanup_on_disconnect()`: Verify WebSocket teardown and lock release upon client disconnect.

### 3. Load Testing Benchmarks
- **Scenarios**: 100, 500, 1,000, and 5,000 concurrent active sessions sending 1 prompt every 10 seconds.
- **Pass Criteria**: $P_{95} \text{ TTS Latency} < 250\text{ms}$, $P_{99} < 400\text{ms}$, 0 socket leak accumulation.

### 4. Chaos Testing Suite
- **Chaos Case A (Upstream Kill)**: Simulate sudden Cartesia API drop mid-sentence. Verify graceful REST fallback without hanging playback queues.
- **Chaos Case B (High Packet Loss / Latency)**: Inject 20% packet drop and 200ms network jitter. Verify ping/pong half-open detection closes dead sockets.
- **Chaos Case C (Rapid Interruption Spam)**: Fire 50 user interrupt commands per second during active streaming. Verify lock integrity and queue cleanup.

---

## 10. Expanded Observability & Telemetry Schema

The following structured telemetry events must be emitted to `telemetry_bus`:

```json
{
  "event": "tts_ws_metrics",
  "session_id": "sess_9876",
  "turn_id": "4",
  "detail": {
    "ws_connect_ms": 142,
    "ws_prewarm_hit": true,
    "ws_reuse_count": 5,
    "ws_reconnect_count": 0,
    "first_push_ms": 12,
    "first_audio_ms": 215,
    "playback_queue_depth": 3,
    "active_session_sockets": 142,
    "idle_reaped_count": 12
  }
}
```

- **Key Gauges Monitored in Prometheus/Grafana**:
  - `voice_agent_active_websockets_total`
  - `voice_agent_tts_first_audio_latency_ms` (Histogram $P_{50}, P_{90}, P_{99}$)
  - `voice_agent_prewarm_hit_ratio`
  - `voice_agent_reconnect_failures_total`
  - `voice_agent_idle_sockets_reaped_total`

---

## 11. Production Deployment & Rollout Strategy

To safely roll out latency optimizations to production:

```
[Phase 1: Feature Flag (0%)] ---> [Phase 2: Canary (5%)] ---> [Phase 3: Rollout (50%)] ---> [Phase 4: Full (100%)]
```

1. **Feature Flag Control**: `enable_tts_ws_pooling: true/false` in `voice_settings.yaml`.
2. **Canary Deployment**: Deploy to 5% of incoming user sessions. Monitor $P_{99}$ latency and socket leak metrics for 24 hours.
3. **Rollback Strategy**: Automatic rollback to REST fallback (`enable_tts_ws_pooling: false`) if $P_{99}$ latency exceeds 800ms or error rate exceeds 1%.

---

## 12. Operational Background Services

The system utilizes 4 dedicated background maintenance routines:

1. **Connection Reaper Task (`_idle_reaper_loop`)**: Runs every 15s in `TTSWorker` to close idle WebSockets (>60s).
2. **Heartbeat Health Checker**: Sends WS ping frames every 15s during idle states to detect half-open TCP links.
3. **Session Sweeper**: Periodic cleanup of stale cancellation tokens and turn IDs in `cancel_token.py`.
4. **Metrics Aggregator**: Flushes pooled telemetry events to disk/Prometheus gateway every 5 seconds.

---

## 13. Future Architecture Extensibility

To support multi-provider TTS and advanced voice synthesis without structural refactoring:

- **`BaseTTSClient` Abstraction**: Define a standard async provider interface (`connect()`, `push_sentence()`, `receive_chunks()`, `close()`).
- **Multi-Provider Failover**: Implement automatic fallback from Cartesia Sonic 3.5 to Deepgram Aura or ElevenLabs Turbo if primary provider circuit breaker flips `OPEN`.
- **Emotion & Voice Cloning Tags**: Standardize SSML/break tag parsers in `tts_client.py` for dynamic prosody tuning across providers.

---

## 14. Architecture Assumptions & Trade-Offs

### Assumptions
1. Cartesia WebSocket connections support multi-turn lifetime when context IDs are managed cleanly.
2. Network infrastructure between Gateway and Cartesia maintains $<50\text{ms}$ RTT.

### Operational Constraints & Trade-Offs
- **Memory vs Latency Trade-Off**: Retaining pre-warmed WebSockets consumes ~15KB RAM per idle session to deliver <250ms first-audio latency. The 60-second idle reaper caps memory consumption safely.
- **Thread Pool Overhead**: Python GIL necessitates thread-pool offloading for synchronous Cartesia SDK calls. Transitioning to native async Cartesia client remains the ultimate long-term milestone.

---

## 15. Additional Recommendations

> [!IMPORTANT]
> **1. OS File Descriptor Tuning**:
> Set `ulimit -n 65535` on host Linux instances to ensure system handles 5,000+ concurrent TCP/WebSocket sockets without OS-level `EMFILE` errors.

> [!TIP]
> **2. TCP Keep-Alive Configuration**:
> Enable TCP Keep-Alive on the underlying Python socket options (`SO_KEEPALIVE`, `TCP_KEEPIDLE=30`, `TCP_KEEPINTVL=10`, `TCP_KEEPCNT=3`) to detect network disconnects at the kernel layer.
