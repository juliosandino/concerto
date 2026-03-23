# Plan: Test Scheduling Service (TSS) — "Concerto"

## TL;DR

Build a Python monorepo with 4 packages (shared, controller, agent, chaos) using FastAPI+WebSockets for real-time agent communication, PostgreSQL for persistence, Textual for a live TUI dashboard, all orchestrated via Docker Compose. The controller is the central scheduler that routes test jobs to compatible agents, monitors heartbeats, and re-queues on failure. The chaos simulator stress-tests the system by spawning mock agents with randomized failure profiles.

---

## Architecture Overview

```
┌──────────────┐       WebSocket        ┌──────────────────┐
│  Agent(s)    │◄──────────────────────►│   Controller     │
│  (testbeds)  │  register/heartbeat/   │   (scheduler)    │
│              │  job assignment         │                  │
└──────────────┘                        │  ┌────────────┐  │
                                        │  │ Dispatcher  │  │──► PostgreSQL
┌──────────────┐       WebSocket        │  │ Heartbeat   │  │
│  Chaos       │  spawns mock agents ──►│  │ Monitor     │  │
│  Simulator   │                        │  └────────────┘  │
└──────────────┘                        │  ┌────────────┐  │
                                        │  │ REST API    │  │
┌──────────────┐   REST / WebSocket     │  │ (jobs, fleet│  │
│  TUI         │◄──────────────────────►│  │  status)    │  │
│  Dashboard   │                        │  └────────────┘  │
└──────────────┘                        └────────────────── ┘
```

---

## Decisions

- **Language:** Python 3.12+
- **Package manager:** uv (workspace mode)
- **Communication:** WebSockets (FastAPI) for agent↔controller; REST for job submission & fleet queries
- **Database:** PostgreSQL (via SQLAlchemy async + asyncpg)
- **TUI:** Textual (live dashboard showing fleet status, job queue, logs)
- **Containerization:** Docker Compose (controller, postgres, and optionally agent/chaos)
- **Monorepo:** 4 packages — `shared`, `controller`, `agent`, `chaos`

---

## Repository Structure

```
concerto/
├── pyproject.toml                  # uv workspace root
├── docker-compose.yml
├── Dockerfile.controller
├── Dockerfile.agent
├── Dockerfile.chaos
├── packages/
│   ├── shared/
│   │   ├── pyproject.toml
│   │   └── src/concerto_shared/
│   │       ├── __init__.py
│   │       ├── models.py          # Pydantic models (Agent, Job, etc.)
│   │       ├── enums.py           # AgentStatus, JobStatus, Product enums
│   │       └── messages.py        # WebSocket message schemas (register, heartbeat, job_assign, etc.)
│   ├── controller/
│   │   ├── pyproject.toml
│   │   └── src/concerto_controller/
│   │       ├── __init__.py
│   │       ├── main.py            # FastAPI app + lifespan (starts heartbeat monitor)
│   │       ├── config.py          # Settings via pydantic-settings
│   │       ├── db/
│   │       │   ├── __init__.py
│   │       │   ├── models.py      # SQLAlchemy ORM models
│   │       │   ├── session.py     # async engine + session factory
│   │       │   └── migrations/    # Alembic migrations (optional)
│   │       ├── api/
│   │       │   ├── __init__.py
│   │       │   ├── jobs.py        # POST /jobs, GET /jobs, GET /jobs/{id}
│   │       │   ├── agents.py      # GET /agents, GET /agents/{id}
│   │       │   └── ws.py          # WebSocket endpoint /ws/agent
│   │       ├── scheduler/
│   │       │   ├── __init__.py
│   │       │   ├── dispatcher.py  # Job→Agent matching + assignment logic
│   │       │   └── heartbeat.py   # Background task: detect stale agents, re-queue jobs
│   │       └── dashboard/
│   │           ├── __init__.py
│   │           └── app.py         # Textual TUI app (fleet view, job queue, logs)
│   ├── agent/
│   │   ├── pyproject.toml
│   │   └── src/concerto_agent/
│   │       ├── __init__.py
│   │       ├── main.py            # Entry point: connect, register, heartbeat loop, job execution
│   │       ├── config.py          # Agent settings (id, capabilities, controller URL)
│   │       ├── client.py          # WebSocket client (connect, send, receive)
│   │       └── executor.py        # Simulated test execution (sleep + random success/failure)
│   └── chaos/
│       ├── pyproject.toml
│       └── src/concerto_chaos/
│           ├── __init__.py
│           ├── main.py            # CLI entry: launch N agents with chaos profiles
│           ├── config.py          # Chaos settings (num agents, failure rates, etc.)
│           ├── profiles.py        # Failure profile definitions (dropout, slow heartbeat, job crash)
│           └── simulator.py       # Spawns concurrent mock agents using asyncio tasks
├── tests/
│   ├── conftest.py                # Shared fixtures (test DB, mock WS server)
│   ├── unit/
│   │   ├── test_dispatcher.py
│   │   ├── test_heartbeat.py
│   │   ├── test_messages.py
│   │   └── test_executor.py
│   └── integration/
│       ├── test_agent_lifecycle.py     # Register → assign → complete flow
│       ├── test_failover.py           # Agent drops → job re-queued
│       └── test_chaos.py             # Multi-agent chaos scenario
└── README.md
```

---

## Steps

### Phase 1: Project Scaffolding

1. **Create uv workspace root** — `pyproject.toml` at repo root with `[tool.uv.workspace]` referencing all 4 packages under `packages/*`.
2. **Create shared package** — `packages/shared/` with Pydantic models, enums (`AgentStatus: ONLINE | BUSY | OFFLINE`, `JobStatus: QUEUED | ASSIGNED | RUNNING | COMPLETED | FAILED`, `Product` enum), and WebSocket message schemas (typed dict/Pydantic: `RegisterMessage`, `HeartbeatMessage`, `JobAssignMessage`, `JobStatusMessage`).
3. **Create controller package skeleton** — `packages/controller/` with FastAPI app, config, empty route/WS modules. Depends on `concerto-shared`.
4. **Create agent package skeleton** — `packages/agent/` with entry point and config. Depends on `concerto-shared`.
5. **Create chaos package skeleton** — `packages/chaos/` with entry point. Depends on `concerto-shared` and `concerto-agent`.
6. **Docker Compose** — `docker-compose.yml` with services: `postgres` (image: postgres:16), `controller` (build from Dockerfile.controller), and optional `agent`/`chaos` services.
7. **Verify** — `uv sync` succeeds, `docker compose up postgres` starts, all packages importable.

### Phase 2: Database Layer (Controller)

8. **SQLAlchemy async models** — Define `AgentRecord` (id, name, capabilities JSON, status, last_heartbeat timestamp, current_job_id) and `JobRecord` (id, product, status, assigned_agent_id, created_at, started_at, completed_at, result) in `controller/db/models.py`.
9. **Session factory** — Async engine with `asyncpg`, `async_sessionmaker`, startup hook to create tables (or Alembic for migrations).
10. **Config** — `pydantic-settings` for `DATABASE_URL`, `HEARTBEAT_TIMEOUT_SEC`, `HEARTBEAT_CHECK_INTERVAL_SEC`, `WS_HOST`, `WS_PORT`.

### Phase 3: WebSocket Protocol & Agent Registration (*depends on Phase 1 & 2*)

11. **Controller WS endpoint** (`/ws/agent`) — Accept connections, wait for `RegisterMessage`, validate, persist agent in DB as `ONLINE`, add to in-memory connection map (`dict[agent_id, WebSocket]`). On disconnect: mark agent `OFFLINE`, re-queue any assigned job.
12. **Agent WS client** (`client.py`) — Connect to controller, send `RegisterMessage` with agent ID + list of supported `Product` values. Handle reconnection with exponential backoff.
13. **Heartbeat loop** — Agent sends `HeartbeatMessage` every N seconds. Controller updates `last_heartbeat` timestamp on receipt.

### Phase 4: Job Submission & Intelligent Routing (*depends on Phase 3*)

14. **REST endpoints** — `POST /jobs` (accept product type, return job ID), `GET /jobs` (list all with filters), `GET /jobs/{id}`.
15. **Dispatcher** (`dispatcher.py`) — On new job or agent becoming available: query for `ONLINE` agents whose capabilities include the job's product, pick one (e.g., least-recently-used or random), send `JobAssignMessage` over its WebSocket, update DB (agent→BUSY, job→ASSIGNED).
16. **Agent job execution** — On receiving `JobAssignMessage`: send `JobStatusMessage(RUNNING)`, simulate work (async sleep), send `JobStatusMessage(COMPLETED|FAILED)`. Controller updates DB accordingly; on completion, mark agent `ONLINE` and trigger dispatcher for queued jobs.

### Phase 5: Resiliency — Heartbeat Monitor (*depends on Phase 3 & 4*)

17. **Heartbeat monitor** (`heartbeat.py`) — Background `asyncio.Task` started in FastAPI lifespan. Every `HEARTBEAT_CHECK_INTERVAL_SEC`, query agents where `status != OFFLINE` and `last_heartbeat < now - HEARTBEAT_TIMEOUT_SEC`. For each stale agent: close WebSocket, mark `OFFLINE`, re-queue any `ASSIGNED`/`RUNNING` job (set job back to `QUEUED`, clear `assigned_agent_id`), trigger dispatcher.
18. **Race condition safety** — Use DB-level row locking (`SELECT ... FOR UPDATE`) or optimistic concurrency (version column) when transitioning job/agent states to prevent double-assignment.

### Phase 6: TUI Dashboard (*parallel with Phase 5*)

19. **Textual app** (`dashboard/app.py`) — Connects to controller via REST (polling) or a dedicated WebSocket stream. Displays:
    - **Fleet table:** Agent ID, status (color-coded), capabilities, current job, last heartbeat age.
    - **Job queue table:** Job ID, product, status, assigned agent, timestamps.
    - **Event log:** Scrolling log of events (registrations, assignments, failures, re-queues).
20. **CLI entry point** — `concerto-dashboard` command (or `python -m concerto_controller.dashboard`).

### Phase 7: Chaos Simulator (*depends on Phase 3*)

21. **Failure profiles** (`profiles.py`) — Define dataclasses: `DropoutProfile` (probability of sudden disconnect, min/max uptime), `SlowHeartbeatProfile` (delayed heartbeats), `JobFailureProfile` (probability of job failure), `FlappingProfile` (rapid connect/disconnect cycles).
22. **Simulator** (`simulator.py`) — Accepts config (num agents, product distribution, failure profile mix). For each mock agent: create an asyncio task that runs a modified agent loop applying its failure profile. Use `asyncio.TaskGroup` for structured concurrency.
23. **CLI entry point** — `concerto-chaos` command with args: `--agents N`, `--chaos-level low|medium|high`, `--controller-url ws://...`.

### Phase 8: Testing (*parallel with Phase 6 & 7*)

24. **Unit tests** — `test_dispatcher.py` (matching logic, no-compatible-agent case, re-dispatch on free), `test_heartbeat.py` (stale detection, re-queue), `test_messages.py` (serialization round-trip), `test_executor.py` (completion/failure paths).
25. **Integration tests** — Use `httpx.AsyncClient` + `websockets` against a real FastAPI test server with a test PostgreSQL (via `testcontainers-python` or test Docker Compose). Test full lifecycle: register → submit job → assign → complete. Test failover: register → assign → kill WS → verify re-queue.
26. **Pytest config** — `pytest-asyncio` for async tests, `pytest-cov` for coverage.

### Phase 9: Polish & Demo Prep

27. **README** — Setup instructions (uv, Docker Compose), how to run each service, how to launch chaos demo.
28. **Docker Compose finalization** — Ensure `docker compose up` brings up controller + postgres + optional chaos simulator, with health checks and proper startup ordering.
29. **Demo script** — A shell script or Makefile target that: starts the stack, submits a batch of jobs, launches chaos simulator, opens TUI dashboard.

---

## Relevant Files

- `pyproject.toml` (root) — uv workspace definition
- `packages/shared/src/concerto_shared/models.py` — Core Pydantic models shared across all services
- `packages/shared/src/concerto_shared/messages.py` — WebSocket message protocol definitions
- `packages/controller/src/concerto_controller/main.py` — FastAPI app with lifespan hooks
- `packages/controller/src/concerto_controller/api/ws.py` — WebSocket endpoint, connection management
- `packages/controller/src/concerto_controller/scheduler/dispatcher.py` — Job→Agent routing algorithm
- `packages/controller/src/concerto_controller/scheduler/heartbeat.py` — Stale agent detection + re-queue
- `packages/controller/src/concerto_controller/db/models.py` — SQLAlchemy ORM (AgentRecord, JobRecord)
- `packages/controller/src/concerto_controller/dashboard/app.py` — Textual TUI
- `packages/agent/src/concerto_agent/client.py` — WebSocket client with reconnection
- `packages/agent/src/concerto_agent/executor.py` — Simulated test job runner
- `packages/chaos/src/concerto_chaos/simulator.py` — Mock agent spawner with failure profiles
- `docker-compose.yml` — Orchestration for all services + PostgreSQL

---

## Verification

1. **Scaffolding:** `uv sync` succeeds; `uv run python -c "import concerto_shared, concerto_controller, concerto_agent, concerto_chaos"` works.
2. **DB:** `docker compose up postgres` starts; controller creates tables on startup.
3. **Registration:** Start controller + one agent → agent appears as ONLINE in `GET /agents`.
4. **Job routing:** `POST /jobs` with a matching product → job assigned to agent → agent completes → job status is COMPLETED.
5. **Failover:** Kill agent mid-job → heartbeat monitor marks agent OFFLINE within timeout → job re-queued → new agent picks it up.
6. **TUI:** Launch dashboard → see live fleet status, job queue updates.
7. **Chaos:** Run `concerto-chaos --agents 10 --chaos-level high` → observe jobs being assigned, agents dropping, jobs re-queuing, all visible in TUI.
8. **Tests:** `uv run pytest tests/ -v --cov` passes with reasonable coverage.

---

## Key Dependencies

- `fastapi`, `uvicorn[standard]` — HTTP + WebSocket server
- `websockets` — Client-side WebSocket (for agent)
- `sqlalchemy[asyncio]`, `asyncpg` — Async PostgreSQL ORM
- `pydantic`, `pydantic-settings` — Config + data models
- `textual` — TUI dashboard
- `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx` — Testing
- `testcontainers` — Integration test PostgreSQL

---

## Further Considerations

1. **Controller WS event stream for TUI** — The TUI can poll REST, but a dedicated `/ws/dashboard` endpoint that pushes state-change events would give a smoother live experience. Recommend adding this alongside REST. Should we include this?
2. **Agent ID generation** — Agents could self-assign a UUID, or the controller could assign one on registration. Self-assigned is simpler and allows reconnection to the same identity. Recommend self-assigned UUID with optional human-readable name.
3. **Job priority / ordering** — Requirements don't mention priority. Recommend FIFO for now, with a `priority` field on jobs as a future extension.
