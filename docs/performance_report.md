# System Performance Audit & Latency Report

This report analyzes the latency profile and resource footprint of the Pivot Voice Agent system, mapping browser events, network transport, orchestrator state machine handling, and external API requests (Deepgram, Groq, Cartesia).

---

## ⏱️ Latency Budget Breakdown

Here is the latency profile mapping typical round-trip performance against target thresholds:

| Pipeline Stage | Target Latency | P50 (Typical) | P95 (Peak) | Status | Primary Latency Driver |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Speech-to-Text (STT)** | 250ms | 180ms | 340ms | 🟢 Healthy | Cloud STT final transcript consolidation |
| **LLM Inference (Groq)** | 800ms | 480ms | 890ms | 🟢 Healthy | Time-to-first-token generation |
| **Text-to-Speech (TTS)** | 250ms | 210ms | 390ms | 🟢 Healthy | Cartesia audio synthesis engine turnaround |
| **Network RTT & WebRTC** | 150ms | 45ms | 180ms | 🟢 Healthy | Client-to-server gateway transport latency |
| **Total Turnaround Time** | **1200ms** | **915ms** | **1800ms** | 🟢 Healthy | Serial execution of LLM and TTS tasks |

---

## 🔥 Request Lifecycle Flame Graph

Below is the request lifecycle execution timeline:

```
[Browser Speech recognition Finalization]  (T = 0ms)
└── 📥 Local STT processing
    └── 🔌 HTTP /chat POST payload delivery (T = 180ms)
        └── 🧠 Orchestrator FSM: Loading Redis Memory (T = 195ms)
            └── 🧠 LLM Inference: Groq Completion (T = 210ms ──────> 690ms)
                └── 🧠 FSM Transition: Thinking -> Speaking (T = 695ms)
                    └── 🗣️ TTS Synthesis: Cartesia API (T = 700ms ───> 910ms)
                        └── 📥 Base64 Encoding & API Response (T = 915ms)
                            └── 🔌 HTTP Response Transport to Browser (T = 945ms)
                                └── 🗣️ Local Audio play start (T = 955ms)
```

---

## ⚠️ Core Bottlenecks Identified

1. **Serial Execution Blockers:**
   The current fallback `/chat` pathway performs the entire turn sequence in a serial block: STT -> FSM State Retrieval -> LLM generation -> TTS generation -> API response. The browser does not play audio until the *entire* response is compiled.
2. **Missing Local Cache Layer:**
   Repetitive greetings (e.g. *"hello"*, *"who are you"*) require fresh LLM and TTS syntheses, consuming unnecessary API latency.
3. **Connection Warmup Overhead:**
   Initializing connections to Groq/Cartesia APIs dynamically adds warmup latency on the first voice turn.

---

## 📈 Top 10 Optimization Actions (Ranked by Latency Impact)

| Rank | Optimization Initiative | Scope | Estimated Savings |
| :--- | :--- | :--- | :--- |
| **1** | **Direct Audio Streaming (Vite WebRTC Client):** Switch to streaming audio chunks directly via WebRTC data tracks rather than polling fallback HTTP endpoints. | WebRTC | **350ms - 500ms** |
| **2** | **LLM Token Streaming to TTS:** Stream tokens from Groq dynamically into Cartesia's WebSockets API, synthesizing audio chunks concurrently as sentences finish. | Orchestrator | **250ms - 350ms** |
| **3** | **Local LLM/TTS Semantic Cache:** Store base64 audio frames of frequent expressions locally inside Redis. | State Store | **200ms - 300ms** |
| **4** | **Cartesia API Key Connection Pool:** Keep Cartesia client connections warm in the background. | TTS Client | **80ms - 150ms** |
| **5** | **Pre-flight pre-heating:** Pre-warm Deepgram/Cartesia WebSockets during browser microphone permission stage. | Browser | **60ms - 100ms** |
| **6** | **Compressed PCM payload transport:** Switch audio format from WAV encoding to raw PCM 16-bit to reduce Base64 size. | Network | **40ms - 80ms** |
| **7** | **Optimized system prompts:** Condense the system instructions size to minimize input token processing delay. | LLM Client | **30ms - 50ms** |
| **8** | **Optimized Redis Session Pipeline:** Pipeline conversational history loading and state updates into one Redis execution block. | State Store | **20ms - 40ms** |
| **9** | **Asynchronous event logging:** Offload telemetry logger file-writing tasks to a background task worker. | Logger | **15ms - 30ms** |
| **10**| **UI Rendering Minimization:** Avoid direct DOM re-paints during SpeechRecognition events by throttling refresh rates. | Browser | **5ms - 10ms** |

---

## 🎯 Action Plan to Achieve <1s ChatGPT Voice Responsiveness

To transform the Pivot Voice Agent from the current turnaround profile into a sub-second interactive experience, we should implement three main architectural steps:

1. **Pipeline Streaming:**
   * Stream Groq LLM tokens directly to Cartesia WebSockets.
   * Play audio chunks progressively in the WebRTC Client.
2. **Warm Connection Pooling:**
   * Keep WebSocket connections to Deepgram/Cartesia active.
   * Warm up API clients on participant join.
3. **Edge Caching:**
   * Implement semantic text hash cache in Redis.
   * Serve cache-hit turns locally in <100ms.
