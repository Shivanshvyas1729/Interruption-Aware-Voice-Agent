# 🎙️ Pivot: Interruption-Aware Voice Agent

Pivot is a real-time voice agent designed to handle natural human-agent conversations, supporting barge-in, interruption classification, contextual recovery, failovers, and low-latency response processing.

> [!IMPORTANT]  
> This repository is a **phase-gated scaffold**. Every file is set up as a stub containing comments and docstrings detailing its implementation scope. You should build the agent progressively, phase by phase, using the verified reference architectures.

---

## 🚀 Getting Started

1. **Read the Reference Build Plan:** Check [rules/pivot-build-plan.md](file:///c:/Users/DELL/Desktop/pivot/rules/pivot-build-plan.md) in full. It holds the canonical port/edge mapping and detailed steps.
2. **Consult the Project Memory:** Read [PROJECT.md](file:///c:/Users/DELL/Desktop/pivot/PROJECT.md) for architecture diagrams, directory structures, and coding standards.
3. **Track Tasks:** Refer to [TASKS.md](file:///c:/Users/DELL/Desktop/pivot/TASKS.md) to check progress and see immediate next steps.
4. **Follow the Phased Prompts:** Use [rules/PHASE_PROMPTS.md](file:///c:/Users/DELL/Desktop/pivot/rules/PHASE_PROMPTS.md) one phase at a time.
5. **Run the Test Gates:** Ensure your code passes cumulative tests before proceeding:
   ```bash
   pytest tests/ -q
   ```

---

## 📂 Layout Overview

```
pivot/
├── client/                 # React+VAD voice client & Phase 1 minimal harness
├── services/               # Microservices architecture (edge, media, orchestrator, workers)
├── common/                 # Shared logging, config, schema, and utility libraries
├── tests/                  # Cumulative test suite for all implementation phases
├── docs/                   # Diagram sources and architecture documentation
├── rules/                  # Development rules, prompts, and build plans
└── scripts/                # Architecture validation and bootstrap automation scripts
```

---

## ⚖️ Ground Rules

* 🟢 **No Breaks Between Phases:** A phase is only considered complete once the *entire cumulative regression suite* (all tests for prior phases) passes in a single run.
* 📦 **Additive and Isolated Progress:** Build one capability per phase. Never implement future-phase features early.
* 📝 **Structured Logging:** Log JSON lines with `session_id`, `turn_id`, `latency_ms`, and `event` for tracing.
* 🔒 **Secrets Security:** Never hardcode secrets. Ensure keys are loaded dynamically and scrubbed from logs.
