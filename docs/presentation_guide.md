# 🎤 Judge Presentation & Pitch Guide: Pivot

Use this guide to walk a panel of judges through the architecture, design choices, and phased deliverables of Pivot.

---

## 💡 The Core Value Proposition (Elevator Pitch)

> "Traditional voice assistants (like Siri or Alexa) only support basic **barge-in detection**—they go silent when you make a sound, throw away their current progress, and force you to start the turn over. **Pivot is different.** It is a real-time, **interruption-aware voice agent** that handles conversation dynamically. When interrupted, it:
> 1. Gracefully stops audio generation mid-sentence.
> 2. Classifies the *intent* of the interruption (e.g., a correction vs. a clarification vs. a backchannel).
> 3. Tracks exactly which words were spoken vs. cut off.
> 4. Merges the new interruption context, executing a tailored recovery strategy to continue the flow seamlessly."

---

## 🏛️ System Architecture Highlights
* **WebRTC & LiveKit (Data Plane):** High-speed media transport that streams raw mic audio to the server and receives TTS synthesized audio bytes.
* **Deepgram STT & Cartesia TTS:** Fast transcription and speech synthesis. Cartesia supports active stream control to kill audio streams mid-stream.
* **Orchestrator FSM (Control Plane):** A python control layer running a LangGraph Finite State Machine. It processes text transcripts and events, *never touching raw audio*, ensuring latency is spent where it counts (intelligence).

---

## 🚀 Phase-by-Phase talking points

### 🎛️ Phase 0: Foundations & Architecture Lock-In
* **Pitch focus:** engineering rigor, preventive testing, and fixing system decay.
* **Points to speak:**
  > "Before writing a single line of voice code, we audited the initial architectural ports. We found that **22 out of 35 connections** violated basic port direction rules (inputs used as outputs, generic ports misused). We built `validate_architecture.py` to turn this manual audit into a permanent CI check, ensuring no future developer can push an invalid port connection to main."

---

### 🔊 Phase 1: Minimal Single-Turn Voice Agent
* **Pitch focus:** pipeline proof, latency baseline.
* **Points to speak:**
  > "We proved the round-trip audio path (WebRTC ↔ LiveKit ↔ Deepgram ↔ Orchestrator ↔ Cartesia). We isolated pipeline latency from frontend complexity by using a bare-bones HTML join test harness. Every hop logs its latency from day one, allowing us to catch performance regressions immediately."

---

### 🧠 Phase 2: Multi-Turn Conversation State
* **Pitch focus:** session persistence, stateless backend.
* **Points to speak:**
  > "We moved session history out of memory and into a stateless Redis state-store. If our orchestrator service crashes mid-call, the session context survives. The orchestrator pulls historical turns on each step, ensuring the LLM understands conversation history."

---

### 🛑 Phase 3: Client-Side VAD & Barge-In Kill Signal
* **Pitch focus:** the barge-in kill switch.
* **Points to speak:**
  > "We promoted our client to React and added local **Silero VAD** (Voice Activity Detection). When local speech is detected, the client ducks local speaker audio instantly. Simultaneously, the orchestrator triggers Cartesia's control endpoint to kill the audio stream server-side. We hit our first latency target here: stopping the agent in **under 300ms**."

---

### 🏷️ Phase 4: Interruption Classification
* **Pitch focus:** context filtering, identifying backchannels.
* **Points to speak:**
  > "Not all user sounds are interruptions. Saying 'uh-huh' or 'yeah' (backchanneling) should be filtered. We implemented a 200ms sustained-speech window combined with a classifier that filters backchannels and categorizes true interruptions into 5 intents (Correction, Topic-change, Clarification, Stop, or Add-on) with over 85% accuracy."

---

### 🔄 Phase 5: Context Capture & Resolution Strategy
* **Pitch focus:** word-level recovery, dynamic response adjustment.
* **Points to speak:**
  > "This is where the magic happens. We wire Cartesia's word timestamps to map out exactly what words were spoken versus cut off. We then merge this context according to the interruption type. For example, a **Correction** discards unspoken words and regenerates the response, while a **Clarification** answers the query and resumes the remainder of the original response."

---

### 🛠️ Phase 6: Tool-Calling & Mid-Call Interruption Policy
* **Pitch focus:** handling background jobs safely.
* **Points to speak:**
  > "We introduced a Celery worker for external API tool calls. If a user interrupts the agent *while* a database lookup or API call is in progress, we don't crash. We execute an explicit policy: **Clarifications** queue behind the job, while **Cancellations** trigger active cancellation handlers to abort the tool execution."

---

### 🛡️ Phase 7: Failover & Semantic Cache
* **Pitch focus:** high availability, low cost/latency.
* **Points to speak:**
  > "To ensure 99.9% uptime, we built LLM failover. If our primary model (Groq) times out, the orchestrator silently routes the request to OpenAI with matching persona rules. We also added a Semantic Cache to answer repeating queries instantly, bypassing LLM generation completely."

---

### 📦 Phase 8: RAG, Guardrails, & Feature Flags
* **Pitch focus:** safe, grounded agent integration.
* **Points to speak:**
  > "We integrated Qdrant for vector RAG retrieval and Enkrypt for safety guardrails. Following clean design patterns, all sponsor libraries are toggleable via feature flags (`*_ENABLED` env vars), so we can bypass them instantly if they degrade latency near release day."

---

### 📊 Phase 9: Concurrency, Observability, & Dashboards
* **Pitch focus:** telemetry tracking, performance dashboards.
* **Points to speak:**
  > "We integrated OpenTelemetry, Loki, and Prometheus to measure latency p95 budgets in real time. We built load-simulation tests to verify that 2–3 concurrent sessions run smoothly without any state leakage or latency spikes."

---

### 🔐 Phase 10: Production Hardening, Consent & Secrets
* **Pitch focus:** enterprise compliance and security audits.
* **Points to speak:**
  > "We implemented API rate limiting, a strict user consent gate blocking STT recording without approval, and migrated all env variables into a secure Secrets Manager wrapper. We ran log audits to guarantee no API keys ever appear in telemetry logs."

---

### 🏁 Phase 11: Demo Readiness
* **Pitch focus:** performance sign-off.
* **Points to speak:**
  > "We finalized our evaluation benchmarks. Our agent achieves a **p95 barge-in latency under 300ms** and an **end-to-end turnaround latency under 1.5s**, fulfilling all non-functional requirements. We have a scripted live demonstration of a multi-turn conversation containing 3 natural interruptions."

---

## 📈 Summary Key Metrics to Impress Judges

| Metric | Target / Benchmark | Implementation Phase |
|---|---|---|
| **Barge-in Kill Latency** | **< 300ms (p95)** | Verified from Phase 3 onward |
| **End-to-End Turnaround** | **< 1.5s (p95)** | Ensured even post-RAG/Guardrails (Phase 8+) |
| **Interruption Classification** | **$\ge$ 85% Accuracy** | Standing eval on 20 scenarios (Phase 4) |
| **Secrets Exposure** | **Zero leakage** | Audited and verified in Phase 10 |



why you used diffrent provider 

Here is why we use different specialized providers for each service instead of a single platform (like OpenAI or LiveKit):

### 1. Ultra-Low Latency & Stream Control (Crucial for Interruption)
* **Cartesia Sonic (TTS):** Specialized TTS engines like Cartesia are optimized for streaming with under 100ms time-to-first-byte. Crucially for this project, Cartesia provides **real-time word-level timestamps** (so we know exactly which word was spoken when cut off) and an **active control/kill signal** to stop the audio stream mid-word. Standard APIs like OpenAI TTS do not support killing an active audio generation in-flight.
* **Deepgram Nova-3 (STT):** Optimized for low-latency streaming transcription via WebSockets, giving us instant word-by-word text updates, which is essential to classify interruptions quickly.
* **Groq (LLM):** Delivers extremely high tokens-per-second (frequently 200+ tps), keeping the conversational turnaround time under our **1.5s p95 target**.

### 2. LiveKit is a Transport Layer, Not an Intelligence Layer
* **LiveKit** acts as the high-speed WebRTC data plane (transporting the audio packets from client to server and back with sub-50ms latency). While LiveKit provides transport wrapper plugins, it does not manage the conversational state machine (FSM), semantic cache, or interruption intent classification. Decoupling the transport (LiveKit) from the intelligence (Orchestrator) keeps our control plane lightweight and fast.

### 3. Redundancy and Risk Mitigation
* **Multi-LLM Failover:** By separating components, we can run Groq as our primary LLM and silently failover to OpenAI (Phase 7) if Groq hits rate limits or experiences downtime.
* **Avoiding Vendor Lock-In:** If a single provider (like OpenAI) experiences an outage, a unified application would crash completely. Decoupling ensures we can swap individual modules (e.g., swapping STT or TTS providers) with zero changes to our core orchestrator logic.