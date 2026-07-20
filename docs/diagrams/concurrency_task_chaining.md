# Concurrency Task Chaining Flow

This diagram illustrates the per-session execution flow of the voice pipeline orchestration services during concurrent requests, task chaining, and error isolation.

```mermaid
sequenceDiagram
    autonumber
    participant STT as STTWorker / FSM
    participant LLM as LLMWorker
    participant TTS as TTSWorker
    participant Play as PlaybackWorker

    STT->>LLM: submit_transcript (Turn 1)
    Note over LLM: spawn task1
    STT->>LLM: submit_transcript (Turn 2)
    Note over LLM: spawn task2 (chains behind task1)
    
    LLM->>LLM: task1 raises RuntimeError (Injected/Failure)
    Note over LLM: task2 catches prior task exception, logs to telemetry, and executes normally

    LLM->>TTS: LLMSentenceChunk (Turn 2)
    Note over TTS: spawn task2 (chains behind prior TTS task)
    
    TTS->>Play: AudioChunk (Turn 2)
    Note over Play: Tagged with Turn 2 ID
```
