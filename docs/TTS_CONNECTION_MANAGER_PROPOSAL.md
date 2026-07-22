# Architecture Proposal Assessment: Dedicated `TTSConnectionManager`

**System**: Interruption-Aware Real-Time Voice Agent Pipeline  
**Component**: TTS Orchestration & Connection Lifecycle  
**Author**: Principal Systems Architect  
**Date**: July 22, 2026  

---

## Executive Summary

The proposal to extract connection lifecycle management from `TTSWorker` into a dedicated `TTSConnectionManager` is **STRONGLY RECOMMENDED FOR IMMEDIATE IMPLEMENTATION**.

Currently, `TTSWorker` suffers from **class responsibility overload**: it simultaneously acts as an asynchronous pipeline stage (queue consumer, task chain manager, sentence ordering orchestrator) AND a low-level network socket manager (WS creation, lock synchronization, race condition event guards, idle socket reapers, session registries).

Extracting `TTSConnectionManager` creates a clean, modular architecture that adheres to the **Single Responsibility Principle (SRP)**, drastically simplifies unit testing, and provides the necessary foundation for future multi-provider TTS failover (Cartesia, Deepgram, ElevenLabs).

---

## 1. Evaluation of Proposed Architecture

```
                    Voice Pipeline / API Gateway
                                 │
                                 ▼
                             TTSWorker (Pipeline Stage)
                                 │
                                 ▼
                     TTSConnectionManager (Singleton / Registry)
                                 │
      ┌──────────────────────────┼──────────────────────────┐
      ▼                          ▼                          ▼
 Connection Lock & Pool     Idle Reaper Task        Circuit Breaker & Backoff
 (`_ws_sessions`)         (`_reaper_loop`)          (`_failure_tracker`)
```

### Responsibility Matrix

| Component | Responsibility Scope |
| :--- | :--- |
| **`TTSWorker`** | Asynchronous queue consumer (`self.input`), task chain ordering (`_session_tasks`), sentence synthesis dispatch, audio chunk output (`self.output`), pipeline stage lifecycle (`start`/`stop`). |
| **`TTSConnectionManager`** | Thread-safe socket caching (`_lock`), in-flight prewarm race guards (`_in_flight_events`), session-scoped continuation state (`_failed_continuation`), connection health metrics, idle socket timeout reaper (`_reaper_loop`), socket teardown (`close_ws_context`). |

---

## 2. Benefits & Trade-Off Analysis

### **Benefits (Why it is a Win)**

1. **Strict Single Responsibility Principle (SRP)**:
   `TTSWorker` focuses solely on message processing and queue pipeline flow. `TTSConnectionManager` focuses solely on network connection pooling and socket health.
2. **Simplified Testing & Mocking**:
   Connection pooling logic can be unit-tested in isolation without instantiating `asyncio.Queue` objects, `PipelineStage` wrappers, or mock worker stages.
3. **Decoupled Provider Abstraction**:
   As new TTS providers (e.g., ElevenLabs Turbo, Deepgram Aura) are introduced, `TTSConnectionManager` can manage provider-agnostic connection pools, allowing `TTSWorker` to switch providers dynamically without socket logic duplication.
4. **Zero Overhead**:
   Internal Python delegation (`connection_manager.acquire()`) adds $<0.001\text{ms}$ overhead—completely imperceptible in audio streaming latency while keeping lock boundaries clean.

### **Trade-Offs & Mitigations**

- **Trade-Off**: Adds one new Python module (`services/orchestrator/tts_connection_manager.py`).
- **Mitigation**: The code refactor is straightforward: lines currently handling `_lock`, `_ws_sessions`, `_reaper_loop`, and `_get_or_create_ws` move cleanly into `TTSConnectionManager` with zero breaking changes to external pipeline APIs.

---

## 3. Public API Specification

The `TTSConnectionManager` class will expose the following clean interface:

```python
class TTSConnectionManager:
    """Thread-safe connection pool, pre-warmer, and idle reaper for TTS WebSockets."""

    def prewarm(self, session_id: str) -> None:
        """Asynchronously pre-warms a WebSocket connection for session_id."""

    def acquire(self, session_id: str, turn_id: str) -> tuple[Any, Any]:
        """Thread-safe retrieval or creation of (ws, ctx) for session_id.
        Waits on in-flight pre-warm events to eliminate connection race conditions."""

    def release(self, session_id: str, failed: bool = False) -> None:
        """Updates last-accessed timestamp or closes socket if marked failed/cancelled."""

    def cleanup(self, session_id: str) -> None:
        """Immediately closes and removes connection upon client disconnect."""

    def mark_continuation_failed(self, session_id: str) -> None:
        """Marks continuation unsupported strictly for session_id."""

    def is_continuation_failed(self, session_id: str) -> bool:
        """Checks if session_id is degraded to sentence fallback."""

    def health_check(self) -> dict[str, Any]:
        """Returns metrics: active_sockets, idle_sockets, in_flight_connects."""

    def shutdown(self) -> None:
        """Closes all open WebSockets and cancels background reaper task."""
```

---

## 4. Final Recommendation & Implementation Strategy

### **Decision: STRONGLY RECOMMENDED — IMPLEMENT NOW**

**Why Now?**
Refactoring connection management into `TTSConnectionManager` *now* (before adding Circuit Breakers, Heartbeat checkers, and Prometheus exporters) prevents `tts_worker.py` from growing into an unmaintainable monolith.

### Implementation Steps:
1. Create `services/orchestrator/tts_connection_manager.py` with `TTSConnectionManager` singleton getter `get_connection_manager()`.
2. Move socket dictionary management, thread locks, race event guards, and idle reaper loops into `TTSConnectionManager`.
3. Refactor `TTSWorker` to acquire/release connections through `get_connection_manager()`.
4. Update `VoicePipeline` and `api_gateway.py` to route pre-warming and cleanup calls to `get_connection_manager()`.
5. Run unit tests to verify zero regressions.
