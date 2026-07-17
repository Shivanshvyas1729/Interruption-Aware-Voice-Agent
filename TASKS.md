# 📋 Project Tasks: Pivot

Use this board to track the implementation status of each build plan phase and outline next actions.

---

## 🚦 Execution Status

| Phase | Goal / Description | Status | Test Command / Notes |
| :---: | :--- | :---: | :--- |
| **Phase 0** | Foundations & Architecture Lock-In | 🟢 *Completed* | `pytest tests/phase0/` |
| **Phase 1** | Minimal Single-Turn Voice Agent | 🔴 *Not Started* | `pytest tests/phase1/` |
| **Phase 2** | Multi-Turn Conversation State | 🔴 *Not Started* | `pytest tests/phase2/` |
| **Phase 3** | Barge-In & React VAD Client | 🔴 *Not Started* | `pytest tests/phase3/` |
| **Phase 4** | Utterance Classification (FSM) | 🔴 *Not Started* | `pytest tests/phase4/` |
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

### 1. Initiate Phase 1 (Minimal Single-Turn Voice Agent)
- [ ] Implement the edge-auth chain: `services/edge-auth/api_gateway.py`, `consent_service.py`, and `token_service.py`.
- [ ] Implement the LiveKit room glue in `services/media-gateway/room_manager.py` and `events.py`.
- [ ] Implement clients in `services/orchestrator/`: `stt_client.py`, `llm_client.py` (primary only), `tts_client.py` (speak only), and `fsm.py` (Phase 1 subset).
- [ ] Build the minimal test harness client in `client/phase1_minimal_harness/`.
- [ ] Un-skip and implement the Phase 1 test `tests/phase1/test_single_turn.py` against a fixture WAV file.
- [ ] Validate everything via `python -m pytest tests/ -q`.
