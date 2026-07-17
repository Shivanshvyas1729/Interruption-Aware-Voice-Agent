# 🛠️ Phase 0 Implementation Guide (Step-by-Step)

If you were to implement Phase 0 from scratch, this is the logical order of dependencies you should follow to build the system foundation.

---

## 1. Centralized Event Vocabulary

**File**

```text
common/events/event_names.py
```

### Purpose

Establishes a single source of truth for all log event names (e.g., `service_started`, `stt_final`, `tts_stopped`) across all microservices using a Python `StrEnum`.

### Why it matters

Ensures consistency across different services and prevents naming drifts (such as one developer logging `tts_stop` and another logging `tts_stopped`), which would break downstream telemetry engines like Loki.

---

## 2. Structured Logging Engine & Secret Scrubbing

**File**

```text
common/logging/logger.py
```

### Purpose

Defines the component-bound logger that formats all stdout prints into machine-parseable JSON lines. It dynamically tags each log line with the active phase and enforces recursive, case-insensitive scrubbing of credentials (replacing them with `[SCRUBBED]`) if:

1. A logging key matches terms like:
   - `api_key`
   - `secret`
   - `password`
   - `token`
2. A logging value contains the exact raw string of a credential loaded from your active environment variables.

### Why it matters

Prevents logs from leaking API secrets during normal operation or failure logs.

---

## 3. Environment & Configuration Settings

**File**

```text
common/config/settings.py
```

### Purpose

Loads settings from the `.env` file using `python-dotenv` into a typed `Settings` dataclass.

It implements **incremental validation** checking the `ACTIVE_PHASE` environment variable.

- For **Phase 0**, it validates basic environment stubs.
- Starting in **Phase 1**, it fails loudly (raising a `ValueError`) if credentials like `GROQ_API_KEY` or `LIVEKIT_URL` are missing.

### Why it matters

Prevents silent runtime failures downstream due to missing environment configurations.

---

## 4. Local Secrets Manager Stub

**File**

```text
services/edge-auth/secrets_manager.py
```

### Purpose

Implements:

```python
get_secret(name)
```

for retrieving credentials.

In Phase 0, it behaves as a **local stub**, reading from configuration settings, while logging secret access events (`secret_accessed`) showing **only the name of the secret**, never the value.

### Why it matters

Standardizes how microservices access keys, so that swapping to a production backend like **AWS Secrets Manager** or **HashiCorp Vault** (planned for **Phase 10**) only requires changing this file's internals, rather than editing downstream microservices.

---

## 5. Service Entry Points & Health Endpoints

**Files**

```text
services/orchestrator/main.py
services/media-gateway/main.py
services/task-worker/main.py
```

### Purpose

Entry point stubs for each of the microservices.

They run lightweight servers using Python's standard `http.server` library (avoiding web framework dependencies in Phase 0) and expose a:

```text
GET /health
```

endpoint returning:

- HTTP `200 OK`
- a `service_started` log event

### Why it matters

Establishes the boilerplate server routing and process initialization patterns.

---

## 6. Architecture Graph Port-Direction Validator

**File**

```text
scripts/validate_architecture.py
```

### Purpose

A command-line script that parses a system architecture JSON graph.

It:

- Resolves the directions of ports.
- Treats ports prefixed with `in-` as **INPUT**.
- Treats ports prefixed with `out-` as **OUTPUT**.
- Allows custom exceptions for generic ports such as database or gateway connections.
- Asserts that:
  - every edge source originates from an output port.
  - every edge target terminates at an input port.

### Why it matters

Prevents architectural rot.

Any updates to the graph structure must pass this script before being pushed to `main`.

---

## 7. Corrected Reference Architecture JSON

**File**

```text
docs/architecture/pivot.json
```

### Purpose

The corrected version of the system architecture graph.

It:

- Resolves all **22** misdirected port/edge connections from the legacy diagram.
- Successfully passes the architecture validator script with **0 violations**.

### Why it matters

Serves as the verified blueprint that the rest of the phases build against.

---

## 8. Phase 0 Test Verification

**File**

```text
tests/phase0/test_health.py
```

### Purpose

The validation gate.

It:

- Spins up all three microservices in background threads.
- Performs HTTP health checks.
- Validates the structured JSON log schema.
- Tests secret scrubbing filters.
- Asserts that the corrected architecture JSON passes validation.

### Why it matters

Proves the health and lock-in of Phase 0.

---

# 📦 `.env` Configuration & Testing Strategy

## 1. What credentials are required in `.env`?

To execute the live pipeline (**Phase 1 onwards**), copy:

```text
.env.example
```

to

```text
.env
```

and configure the following credentials.

### LiveKit

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

**Purpose**

Backs the `media-gateway` service to manage voice rooms and audio transport.

---

### Deepgram

- `DEEPGRAM_API_KEY`

**Purpose**

Used by the STT client to transcribe user speech.

---

### Cartesia

- `CARTESIA_API_KEY`

**Purpose**

Used by the TTS client to generate real-time voice streaming responses.

---

### Groq

- `GROQ_API_KEY`
- `GROQ_MODEL`

**Purpose**

Backs the primary LLM client.

---

### OpenAI

- `OPENAI_API_KEY`
- `OPENAI_FALLBACK_MODEL`

**Purpose**

Backs the fallback failover LLM.

---

### Redis

- `REDIS_URL`

**Purpose**

Connects to the Redis database to store session and conversation history.

---

## 2. How are dummy placeholders handled in test runs?

To ensure developers can run the regression suite:

```bash
pytest tests/
```

without requiring real, active third-party credentials, the project follows the strategy below.

### 2.1 Deterministic Fixtures

Audio-based tests (such as STT/TTS validation) use fixed, local `.wav` files stored under:

```text
tests/fixtures/
```

rather than requesting access to a physical microphone.

This ensures tests remain:

- deterministic
- reproducible
- offline

---

### 2.2 Mocking External APIs

During test execution, network connections to the following providers are mocked:

- Groq
- OpenAI
- Cartesia
- Deepgram

This allows tests to verify:

- Correct request payloads are generated.
- Streaming logic handles token events correctly.
- Latency is monitored.

Because external services are mocked, tests pass successfully even when `.env` contains placeholder credentials such as:

```text
GROQ_API_KEY=dummy_val
```

---

### 2.3 Graceful Failure Strategy

#### During Tests

Mocks are injected, allowing the complete regression suite to run successfully without internet connectivity or valid provider credentials.

#### During Development or Production

The configuration loader (`common/config/settings.py`) validates environment variables according to the active phase.

If it detects a dummy or missing credential while starting a service directly, it immediately raises:

```python
ValueError(...)
```

This provides fast feedback, alerting the developer to update their `.env` before attempting manual smoke tests or deploying the service.