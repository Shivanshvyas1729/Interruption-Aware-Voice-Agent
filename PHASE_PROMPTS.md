# Pivot — Phase Execution Prompts

One self-contained prompt per phase. Run them **in order**, one at a time,
in a fresh or continued coding-agent session (e.g. Claude Code). Do not
start phase N+1's prompt until phase N's is fully done per its own
Definition of Done.

Every prompt below shares the same non-negotiable shape, because that shape
*is* the answer to "check things and remove problems as we go":

1. Implement only the named phase's scope — no more, no less.
2. Un-skip and implement that phase's test in `tests/phaseN/`.
3. Run the **full** cumulative regression suite (`pytest tests/ -q`), not
   just the new test. Every previously-passing test must still pass.
4. While implementing, actively look for and fix problems the same way the
   architecture audit was done — mismatched directions, dangling handlers,
   missing error paths, missing log events — and fix them inside this same
   phase rather than filing them away for later.
5. Update `docs/pivot-build-plan.md` and, if any port/edge/event changed,
   `docs/architecture/` — in the same commit as the code.
6. Commit on a `phase-N-<desc>` branch; only merge after step 3 is green.
   Tag the merge `v0-phaseN`.

If at any point implementing a phase reveals that an earlier phase's code
was wrong (not just incomplete) — fix it now, re-run that earlier phase's
test too, and note the fix at the top of this file's phase entry. Don't
silently patch around an earlier bug.

---

## Phase 0 — Foundations & Architecture Lock-In

```
Implement Phase 0 of Pivot, per docs/pivot-build-plan.md.

Scope (touch only these):
- common/logging/logger.py — structured JSON logger per the schema in
  docs/pivot-build-plan.md section 3. Include the secret-scrub list now,
  not later.
- common/config/settings.py — load .env.example's variables into a typed
  Settings object; fail loudly on missing required-for-this-phase vars.
- common/events/event_names.py — define the Phase 0/1 event constants
  listed in that file's docstring.
- services/orchestrator/main.py, services/media-gateway (add a minimal
  main/health entrypoint if missing), services/task-worker (same) — each
  gets a /health endpoint using the logger above.
- services/edge-auth/secrets_manager.py — implement get_secret() for
  SECRETS_BACKEND=local only (Phase 10 adds the real backends).
- scripts/validate_architecture.py — implement the port-direction
  validator described in its docstring.

Do NOT touch anything audio/LLM/orchestration-logic related — that's Phase 1+.
Do NOT implement api_gateway.py, consent_service.py, or token_service.py
yet — those are Phase 1 (they're part of the client's join flow, not
foundational health/logging plumbing).

Then:
1. Un-skip tests/phase0/test_health.py and implement it for real.
2. Run `pytest tests/ -q` — only Phase 0's test should be un-skipped now;
   everything else remains skipped (that's expected and correct).
3. Fix any problems you find in the stub docstrings while implementing —
   they're specs, not gospel; if a docstring is wrong, fix the docstring
   too.
4. Update docs/pivot-build-plan.md if anything about Phase 0's scope
   changed while implementing.
```

---

## Phase 1 — Minimal Single-Turn Voice Agent

```
Implement Phase 1 of Pivot, per docs/pivot-build-plan.md. Phase 0 must
already be green.

Scope:
- services/edge-auth/api_gateway.py, consent_service.py, token_service.py —
  the real auth chain the client's "Join" button calls: client -> gateway
  -> consent -> token -> back to gateway -> back to client, per the
  corrected wiring in each file's docstring. consent_service.py's Phase 1
  check can be a deliberately simple stub (log it as such, ground rule #6)
  — full consent enforcement is Phase 10, but the SHAPE of the call chain
  must be real now, not hardcoded around.
- services/media-gateway/room_manager.py + events.py — LiveKit room glue,
  using the CORRECTED port wiring documented in that file's docstring
  (not the original uploaded architecture-*.json's literal edges).
- services/orchestrator/stt_client.py, llm_client.py (call_primary only),
  tts_client.py (speak only), fsm.py (Phase 1 subset only).
- client/phase1_minimal_harness/ — bare join/listen/speak test page,
  calling api_gateway's /auth endpoint for a real token, not a hardcoded one.

Do NOT implement: memory (Phase 2), barge-in/VAD (Phase 3), classification
(Phase 4), tools (Phase 6), failover/cache (Phase 7), guardrails/RAG
(Phase 8). If you find yourself reaching for any of these, stop — that's a
sign you've drifted out of Phase 1's scope.

Then:
1. Create a fixture WAV (or reuse an existing sample) under
   tests/phase1/fixtures/ for a simple question.
2. Un-skip and implement tests/phase1/test_single_turn.py against that
   fixture (not a live mic).
3. Run `pytest tests/ -q` — Phase 0 and Phase 1 tests both green, rest
   still skipped.
4. Also do a manual live smoke test via the harness page and confirm you
   can hear a reply — note the result in your phase completion notes.
5. Log every hop's latency now even though no budget is enforced yet.
```

---

## Phase 2 — Multi-Turn Conversation State

```
Implement Phase 2 of Pivot, per docs/pivot-build-plan.md. Phases 0-1 must
already be green.

Scope:
- services/orchestrator/state_store.py — Redis-backed session/turn history.
- Wire fsm.py and llm_client.py to read/write it every turn.
- docker-compose.yml's redis service must actually be used now (uncomment
  nothing — it was never commented; just start relying on it).

Do NOT implement barge-in, classification, or anything past Phase 2.

Then:
1. Un-skip and implement tests/phase2/test_multiturn.py: a 3-turn scripted
   fixture conversation, asserting turn-1 content is present in Redis and
   pulled into turn-2/3's LLM request payload, AND that state survives a
   simulated orchestrator restart.
2. Run `pytest tests/ -q` — Phases 0-2 green.
```

---

## Phase 3 — Client-Side VAD + Barge-In Kill Switch

```
Implement Phase 3 of Pivot, per docs/pivot-build-plan.md. Phases 0-2 must
already be green. This phase implements the single most important fix
from the architecture audit — the missing kill-signal edge.

Scope:
- Promote the client: build out client/src/App.jsx and
  client/src/vad/SileroVAD.js (React + WebRTC + local Silero VAD), porting
  the proven-working logic from client/phase1_minimal_harness rather than
  starting over.
- services/orchestrator/tts_client.py — implement kill().
- services/orchestrator/barge_in.py — implement on_media_event and
  trigger_kill. Any sustained interruption stops TTS immediately (no
  classification yet — that's Phase 4).
- Wire the literal edge: orchestrator.out-tts-ctrl -> cartesia-tts.in-tts-ctrl.

Then:
1. Un-skip and implement tests/phase3/test_barge_in_latency.py.
2. Start asserting the <300ms p95 kill-latency target NOW, not at the end.
   If it's not met, treat that as a Phase 3 blocker, not a note for later.
3. Run `pytest tests/ -q` — Phases 0-3 green.
4. Manually confirm: interrupting the agent mid-sentence in the live
   client actually goes silent.
```

---

## Phase 4 — Interruption Classification + Backchannel Filtering

```
Implement Phase 4 of Pivot, per docs/pivot-build-plan.md. Phases 0-3 must
already be green.

Scope:
- services/orchestrator/interruption_classifier.py — 200ms backchannel
  threshold + 5-type classification (correction, topic-change,
  clarification, stop_cancel, add_on).
- Build the 20 scripted scenario fixtures under tests/phase4/fixtures/
  (per the PRD's eval methodology) if they don't already exist.

Do NOT implement resolution/merge logic yet (Phase 5) — this phase only
proves classification accuracy, it doesn't act on it.

Then:
1. Un-skip and implement tests/phase4/test_classification_eval.py and
   test_backchannel_does_not_trigger_barge_in.py.
2. Assert >=85% accuracy on the 20 scenarios. This is now a STANDING eval —
   re-run it (not just once) in every later phase's regression pass.
3. Run `pytest tests/ -q` — Phases 0-4 green.
```

---

## Phase 5 — Context Capture & Resolution Strategy

```
Implement Phase 5 of Pivot, per docs/pivot-build-plan.md. Phases 0-4 must
already be green.

Scope:
- services/orchestrator/tts_client.py — implement on_word_timestamp.
- services/orchestrator/context_merge.py — implement resolve() with the
  5 distinct strategies documented in that file's docstring.
- Wire fsm.py's `interrupted` state to use context_merge's output to decide
  its next transition.

Then:
1. Un-skip and implement tests/phase5/test_context_merge.py — one
   assertion per interruption type, checking both the strategy chosen and
   the correctness of the merged context (not just "a strategy was picked").
2. Run `pytest tests/ -q` — Phases 0-5 green, including Phase 4's standing eval.
3. Manually rehearse a multi-turn conversation with 3+ interruptions of
   different types and confirm each behaves distinctly.
```

---

## Phase 6 — Tool-Calling + Mid-Call Interruption Policy

```
Implement Phase 6 of Pivot, per docs/pivot-build-plan.md. Phases 0-5 must
already be green.

FIRST: resolve the open decision. Confirm (or adjust) the mid-call
interruption policy table drafted in services/orchestrator/tools.py's
docstring, and copy the FINAL version into docs/pivot-build-plan.md's
"Open Decisions" section, turning it into a real decision record. Do this
before writing implementation code.

Scope:
- services/orchestrator/tools.py — invoke_tool,
  on_interruption_during_call, per the confirmed policy table.
- services/task-worker/worker.py — Celery task definitions, wired via the
  CORRECTED edge (out-api-req -> in-api, not the original uploaded JSON's
  backwards in-api-res source).
- services/external-apis-integration/client.py — the receiving side of
  that edge; decide and document which real/mock external APIs back the
  demo (banking/CRM per the architecture, or a sandbox equivalent).

Then:
1. Un-skip and implement tests/phase6/test_tool_interrupt_policy.py — one
   test per policy-table branch.
2. Run `pytest tests/ -q` — Phases 0-6 green.
```

---

## Phase 7 — LLM Failover + Semantic Cache

```
Implement Phase 7 of Pivot, per docs/pivot-build-plan.md. Phases 0-6 must
already be green.

Scope:
- services/orchestrator/failover.py — call_with_failover, shared persona
  module, silent Groq->OpenAI failover.
- services/orchestrator/cache_client.py — semantic cache lookup/store,
  checked before failover.py is invoked.

Then:
1. Un-skip and implement tests/phase7/test_failover.py (fault-inject
   primary unreachable, assert silent fallback + persona consistency + no
   transcript leakage) and test_cache_hit.py (repeated query is faster).
2. Run `pytest tests/ -q` — Phases 0-7 green.
```

---

## Phase 8 — Guardrails, RAG, Sponsor Tech

```
Implement Phase 8 of Pivot, per docs/pivot-build-plan.md. Phases 0-7 must
already be green.

Scope:
- services/orchestrator/guardrails_client.py — check_input/check_output,
  behind ENKRYPT_ENABLED.
- services/orchestrator/rag_client.py — retrieve, behind RAG_ENABLED.
- Only add Mastra (MASTRA_ENABLED) if Phase 6's hand-rolled tool policy
  has demonstrated a concrete gap it fills — don't add it speculatively.
  If you add it, document WHY in docs/pivot-build-plan.md's Open Decisions.

Then:
1. Un-skip and implement tests/phase8/test_guardrails.py,
   test_rag_grounding.py, and test_no_latency_regression.py.
2. Specifically verify each of ENKRYPT_ENABLED, RAG_ENABLED,
   MASTRA_ENABLED can be flipped to false independently and Phases 1-7
   still pass — this is the feature-flag isolation ground rule #11 requires.
3. Run `pytest tests/ -q` — Phases 0-8 green, including Phase 4's eval and
   Phase 3's latency check (no regression).
```

---

## Phase 9 — Resilience, Failure Modes, Concurrency, Observability

```
Implement Phase 9 of Pivot, per docs/pivot-build-plan.md. Phases 0-8 must
already be green.

Scope:
- Implement each row of the PRD's failure-mode table (STT drop, double
  interruption, both LLMs down, VAD false positive with smooth resume,
  and any others in that table) across fsm.py / barge_in.py / failover.py.
- services/orchestrator/telemetry.py — export_metrics, OTEL wiring (the
  SENDING side).
- services/observability-stack/ingest.py — the actual Prometheus/Grafana/
  Loki/OTEL-collector service (the RECEIVING side) plus the two required
  dashboards (barge-in kill p95, turnaround p95). Uncomment and configure
  the corresponding block in docker-compose.yml.
- services/load-testing-eval/load_test.py — 2-3 concurrent simulated
  sessions via Locust (or equivalent), asserting no cross-session state
  leakage and that latency budgets hold under load.

Then:
1. Un-skip and implement tests/phase9/test_failure_modes.py (one case per
   table row) and test_concurrency.py.
2. Confirm latency budgets hold under concurrent load, not just in isolation.
3. Run `pytest tests/ -q` — Phases 0-9 green.
```

---

## Phase 10 — Security, Consent/Privacy, Secrets Hardening

```
Implement Phase 10 of Pivot, per docs/pivot-build-plan.md. Phases 0-9 must
already be green.

Scope:
- services/edge-auth/secrets_manager.py — implement the "vault" and
  "aws-secrets-manager" SECRETS_BACKEND branches for real; migrate every
  service currently reading secrets via common.config.settings directly
  to call secrets_manager.get_secret() instead, so there's exactly one
  path secrets travel through.
- services/edge-auth/api_gateway.py — enforce auth on every endpoint that
  should have it; add rate limiting.
- services/edge-auth/consent_service.py — replace the Phase 1 stub with
  real, persisted, revocable consent records, and HARD BLOCK: no session
  without recorded consent reaches deepgram-stt.in-audio.
- Audit common/logging/logger.py's scrub-list against EVERY event type
  defined by this point in common/events/event_names.py, not just the
  Phase 0 ones — this is exactly the kind of "silent drift" the
  architecture audit exists to catch, applied to logging instead of ports.

Then:
1. Un-skip and implement tests/phase10/test_security_checklist.py.
2. Run `pytest tests/ -q` — Phases 0-10 green.
```

---

## Phase 11 — Eval Suite, Load Test, Demo-Day Readiness

```
Implement Phase 11 of Pivot, per docs/pivot-build-plan.md. Phases 0-10
must already be green.

Scope:
- services/load-testing-eval/eval_report.py — combines Phase 4's
  classification eval with Phase 9's concurrent-session latency
  measurements into one final report (machine-readable + human-readable).
- Final full run of the 20-scenario interruption eval.
- Final latency report against both PRD non-functional targets, measured
  under concurrent-session conditions (same setup as Phase 9).
- Written demo script: a live multi-turn conversation with 3+ natural
  interruptions across different types.
- Final pass on docs/pivot-build-plan.md and docs/architecture/ to reflect
  the actual as-built system — re-run scripts/validate_architecture.py one
  last time against the real, final port map.

Then:
1. Un-skip and implement tests/phase11/test_full_eval.py.
2. Run `pytest tests/ -q` — ALL phases green, ZERO remaining
   @pytest.mark.skip markers anywhere in tests/. If any remain, that phase
   was not actually finished — go back and finish it before calling this done.
3. Rehearse the demo script against the real system at least once before
   demo day.
```
