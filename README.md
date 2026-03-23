# Concerto — Test Scheduling Service (TSS)

A distributed test scheduling service that manages Hardware-in-the-Loop (HIL) testbed agents. The controller routes test jobs to compatible agents, monitors heartbeats, and automatically re-queues jobs when agents disconnect.

## Architecture

```
┌──────────────┐       WebSocket        ┌──────────────────┐
│  Agent(s)    │◄──────────────────────►│   Controller     │
│  (testbeds)  │  register/heartbeat/   │   (scheduler)    │
│              │  job assignment         │                  │
└──────────────┘                        │  Dispatcher      │──► PostgreSQL
                                        │  Heartbeat Mon.  │
┌──────────────┐       WebSocket        │                  │
│  Chaos       │  spawns mock agents ──►│  REST API        │
│  Simulator   │                        │  (jobs, fleet)   │
└──────────────┘                        │                  │
                                        │                  │
┌──────────────┐   REST (polling)       │                  │
│  TUI         │◄──────────────────────►│                  │
│  Dashboard   │                        │                  │
└──────────────┘                        └──────────────────┘
```

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- Docker & Docker Compose (for PostgreSQL)

## Quick Start

### 1. Install dependencies

```bash
uv sync --all-packages
```

### 2. Start PostgreSQL

```bash
docker compose up -d postgres
```

### 3. Start the Controller

```bash
uv run concerto-controller
```

The controller starts on `http://localhost:8000` with:
- REST API: `GET /agents`, `GET /jobs`, `POST /jobs`
- WebSocket: `ws://localhost:8000/ws/agent`
- Health: `GET /health`

### 4. Start an Agent

In a new terminal:

```bash
AGENT_AGENT_NAME=testbed-01 \
AGENT_CAPABILITIES='["vehicle_gateway","asset_gateway"]' \
uv run concerto-agent
```

### 5. Submit a Test Job

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"product": "vehicle_gateway"}'
```

### 6. Launch the TUI Dashboard

```bash
uv run concerto-dashboard
```

### 7. Run the Chaos Simulator

```bash
uv run concerto-chaos --agents 10 --chaos-level high
```

## Full Stack with Docker Compose

```bash
# Start controller + postgres
docker compose up -d

# Also start chaos simulator
docker compose --profile chaos up -d
```

## Running Tests

```bash
uv run pytest tests/ -v
```

## Project Structure

```
packages/
├── shared/       # Pydantic models, enums, WebSocket message schemas
├── controller/   # FastAPI server, dispatcher, heartbeat monitor, TUI dashboard
├── agent/        # WebSocket client, heartbeat loop, job executor
└── chaos/        # Chaos simulator with failure profiles
```

## API Endpoints

| Method | Path              | Description                          |
|--------|-------------------|--------------------------------------|
| GET    | `/health`         | Health check                         |
| GET    | `/agents`         | List all agents (optional `?status=`)  |
| GET    | `/agents/{id}`    | Get agent by ID                      |
| POST   | `/jobs`           | Submit a new test job                |
| GET    | `/jobs`           | List all jobs (optional `?status=&product=`) |
| GET    | `/jobs/{id}`      | Get job by ID                        |
| WS     | `/ws/agent`       | Agent WebSocket endpoint             |

## Configuration

### Controller (env vars)

| Variable                           | Default | Description                  |
|------------------------------------|---------|------------------------------|
| `CONCERTO_DATABASE_URL`            | `postgresql+asyncpg://concerto:concerto@localhost:5432/concerto` | PostgreSQL connection |
| `CONCERTO_HEARTBEAT_TIMEOUT_SEC`   | `15`    | Seconds before agent is stale |
| `CONCERTO_HEARTBEAT_CHECK_INTERVAL_SEC` | `5` | Heartbeat check frequency    |
| `CONCERTO_WS_HOST`                 | `0.0.0.0` | Server bind host           |
| `CONCERTO_WS_PORT`                 | `8000`  | Server bind port             |

### Agent (env vars)

| Variable                    | Default | Description                    |
|-----------------------------|---------|--------------------------------|
| `AGENT_AGENT_NAME`          | `testbed-01` | Agent display name         |
| `AGENT_CAPABILITIES`        | `["vehicle_gateway","asset_gateway"]` | Supported products |
| `AGENT_CONTROLLER_URL`      | `ws://localhost:8000/ws/agent` | Controller WS URL   |
| `AGENT_HEARTBEAT_INTERVAL_SEC` | `5`  | Heartbeat frequency            |

concerto: A Test Sheduling Service
