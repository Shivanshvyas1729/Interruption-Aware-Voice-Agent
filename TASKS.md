# 📋 Project Tasks: Pivot

Use this board to track the implementation status of each build plan phase and outline next actions.

---

## 🚦 Execution Status

| Phase | Goal / Description | Status | Test Command / Notes |
| :---: | :--- | :---: | :--- |
| **Phase 0** | Foundations & Architecture Lock-In | 🟢 *Completed* | `pytest tests/phase0/` |
| **Phase 1** | Minimal Single-Turn Voice Agent | 🟢 *Completed* | `pytest tests/phase1/` |
| **Phase 2** | Multi-Turn Conversation State | 🟢 *Completed* | `pytest tests/phase2/` |
| **Phase 3** | Barge-In & React VAD Client | 🟢 *Completed* | `pytest tests/phase3/` |
| **Phase 4** | Utterance Classification (FSM) | 🟢 *Completed* | `pytest tests/phase4/` |
| **Phase 5** | Latency Budgeting & Intercept | 🔴 *Not Started* | `pytest tests/phase5/` |
| **Phase 6** | Celery Tool Worker & External APIs | 🔴 *Not Started* | `pytest tests/phase6/` |
| **Phase 7** | LLM Semantic Cache & Failover | 🔴 *Not Started* | `pytest tests/phase7/` |
| **Phase 8** | RAG (Qdrant), Guardrails (Enkrypt), Agent (Mastra) | 🔴 *Not Started* | `pytest tests/phase8/` |
| **Phase 9** | Observability (OTEL/Loki/Prometheus) & Load Sim | 🔴 *Not Started* | `pytest tests/phase9/` |
| **Phase 10** | Production Hardening, Consent & Secrets Manager | 🔴 *Not Started* | `pytest tests/phase10/` |
| **Phase 11** | Evaluation & Latency Budget Sign-Off | 🔴 *Not Started* | `pytest tests/phase11/` |

> **Status Legend:**
> - 🔴 *Not Started* — Awaiting execution
> - 🟡 *In Progress* — Under development
> - 🟢 *Completed* — Fully verified with test gates green

---

## 🎯 Immediate Next Steps

### 1. Initiate Phase 5 (Latency Budgeting & Intercept)
- [ ] Track word boundary timestamps from Cartesia stream in `services/orchestrator/tts_client.py`.
- [ ] Implement `services/orchestrator/context_merge.py` for cutting off agent response at the interrupted word.
- [ ] Perform context merge combining original prompt history, partial playback, and classified user intent.
- [ ] Un-skip and implement `tests/phase5/test_resolution.py` to assert correct context cutting and formatting.
- [ ] Validate everything via `python -m pytest tests/ -q`.