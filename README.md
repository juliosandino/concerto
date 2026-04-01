# Concerto — Test Scheduling Service (TSS)

[![CI](https://github.com/juliosandino/concerto/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/juliosandino/concerto/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/juliosandino/concerto/branch/main/graph/badge.svg)](https://codecov.io/gh/juliosandino/concerto)

A distributed test scheduling service for Hardware-in-the-Loop (HIL) testbed management. Concerto routes test jobs to compatible agents, monitors heartbeats, and automatically re-queues work when agents disconnect — designed for CI-driven and interactive testbed orchestration.

```mermaid
graph LR
    subgraph Agents
        A1[Agent: alpha]
        A2[Agent: beta]
        A3[Agent: sim-*]
    end
    subgraph Controller
        API[REST API :8000]
        WS[WebSocket Hub]
        SCH[Scheduler]
        DB[(PostgreSQL)]
    end
    subgraph Clients
        DASH[TUI Dashboard]
        MCP[MCP Server]
        CURL[curl / CI]
    end
    A1 & A2 & A3 <-->|ws| WS
    WS --- SCH
    SCH --- DB
    API --- DB
    DASH <-->|ws| WS
    MCP -->|http| API
    CURL -->|http| API
```

## Packages

Concerto is a Python monorepo managed with [uv](https://docs.astral.sh/uv/) workspaces. Each package lives under `packages/` and can be installed independently.

| Package | Description |
|---------|-------------|
| **concerto-shared** | Pydantic models, enums (`Product`, `AgentStatus`, `JobStatus`), and WebSocket message schemas shared across all packages. Library only — no CLI. |
| **concerto-controller** | FastAPI server with REST API, WebSocket hub for agents and dashboards, job dispatcher, heartbeat monitor, and Alembic migrations. Entry point: `concerto-controller run`. |
| **concerto-agent** | Testbed agent that connects to the controller via WebSocket, sends heartbeats, receives job assignments, and executes tests. Entry point: `concerto-agent`. |
| **concerto-dashboard** | Textual-based TUI that streams live fleet state over WebSocket — shows agents, jobs, and status in real time. Entry point: `concerto-dashboard`. |
| **concerto-simulator** | Fleet simulator that spawns N virtual agents and queues M jobs for load testing and demos. Entry point: `concerto-simulator`. |
| **concerto-mcp** | [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes the controller REST API as MCP tools for IDE integration (VS Code Copilot, etc.). Entry point: `concerto-mcp`. |
| **concerto-integration-tests** | Docker-based integration test suite that validates the full controller + agent lifecycle against a real PostgreSQL instance. |

## Getting Started

### Prerequisites

- Python 3.12+ (or use Docker for containerised instance)
- PostgreSQL 16+ (or Docker for a containerised instance)

### Installation

Choose one of the three approaches below.

#### Option 1 — uv (recommended)

[uv](https://docs.astral.sh/uv/) is the recommended package manager. It handles the workspace, virtual environment, and lockfile automatically.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install all packages
git clone https://github.com/juliosandino/concerto.git
cd concerto
uv sync --all-packages
```

#### Option 2 — pip

```bash
git clone https://github.com/juliosandino/concerto.git
cd concerto
python -m venv .venv && source .venv/bin/activate

# Install each package in editable mode
pip install -e packages/shared
pip install -e packages/controller
pip install -e packages/agent
pip install -e packages/dashboard
pip install -e packages/simulator
pip install -e packages/mcp
```

#### Option 3 — Docker Compose

No local Python required. Docker Compose builds and runs everything:

```bash
git clone https://github.com/juliosandino/concerto.git
cd concerto

# Start the full stack (postgres, controller, agents, dashboard)
docker compose -f docker/docker-compose.yml up -d

# Attach to the dashboard
docker compose -f docker/docker-compose.yml attach dashboard
```

## Usage

### 1. Start PostgreSQL

If running locally (not Docker Compose), start a PostgreSQL instance:

```bash
docker compose -f docker/docker-compose.yml up -d postgres
```

### 2. Start the controller

```bash
uv run concerto-controller run
```

The controller starts on `http://localhost:8000`.

### 3. Connect an agent

```bash
uv run concerto-agent \
  --agent-name testbed-01 \
  --capability vehicle_gateway \
  --capability asset_gateway
```

Or with environment variables:

```bash
AGENT_AGENT_NAME=testbed-01 \
AGENT_CAPABILITIES='["vehicle_gateway","asset_gateway"]' \
uv run concerto-agent
```

### 4. Submit a test job

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"product": "vehicle_gateway", "duration": 10}'
```

### 5. Launch the TUI dashboard

```bash
uv run concerto-dashboard
```

### 6. Run the simulator

```bash
uv run concerto-simulator --agents 10 --jobs 20 --job-interval 1.5
```

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/agents` | List agents (optional `?status=online\|busy\|offline`) |
| `GET` | `/agents/{id}` | Get agent by UUID |
| `DELETE` | `/agents/{id}` | Remove agent, re-queue its active jobs |
| `POST` | `/jobs` | Queue a new job (`{"product": "...", "duration": ...}`) |
| `GET` | `/jobs` | List jobs (optional `?status=&product=`) |
| `GET` | `/jobs/{id}` | Get job by UUID |
| `WS` | `/ws/agent` | Agent WebSocket endpoint |
| `WS` | `/ws/dashboard` | Dashboard WebSocket endpoint |

### Products

`vehicle_gateway` · `asset_gateway` · `environmental_monitor` · `industrial_gateway`

### Job Statuses

`queued` → `assigned` → `running` → `passed` / `failed`

## MCP Integration

Concerto ships with an MCP server that lets AI assistants (GitHub Copilot, Claude, etc.) interact with your testbed directly from the IDE.

### MCP Tools

| Tool | Description |
|------|-------------|
| `list_agents` | List all agents with optional status filter |
| `get_agent` | Get detailed info for a specific agent |
| `remove_agent` | Remove an agent and re-queue its jobs |
| `list_jobs` | List all jobs with optional status/product filters |
| `get_job` | Get detailed info for a specific job |
| `create_job` | Queue a new test job for a product |

### VS Code Setup

The repository includes `.vscode/mcp.json` which auto-configures the MCP server. On startup it builds the Docker image, then starts the server over stdio:

```json
{
    "servers": {
        "concerto": {
            "command": "bash",
            "args": ["-c", "docker build -f docker/Dockerfile.mcp -t concerto-mcp . >&2 && docker run -i --rm --network ${CONCERTO_NETWORK} -e CONCERTO_CONTROLLER_URL=${CONCERTO_CONTROLLER_URL} concerto-mcp"],
            "env": {
                "CONCERTO_CONTROLLER_URL": "http://localhost:8000",
                "CONCERTO_NETWORK": "host"
            }
        }
    }
}
```

### Prompt Files

Pre-built prompt files in `.github/prompts/` give quick access to common operations:

| Prompt | Usage | Description |
|--------|-------|-------------|
| `/list-agents` | List all agents | Shows connected agents in a table |
| `/get-agent` | `{{agent_id}}` | Get detailed agent info |
| `/remove-agent` | `{{agent_id}}` | Remove an agent and re-queue jobs |
| `/list-jobs` | List all jobs | Shows jobs in a table |
| `/get-job` | `{{job_id}}` | Get detailed job status |
| `/queue-job` | `{{product}}` `{{duration}}` | Queue a test job |

## Configuration

### Controller

| Variable | Default | Description |
|----------|---------|-------------|
| `CONCERTO_DATABASE_URL` | `postgresql+asyncpg://concerto:concerto@localhost:5432/concerto` | PostgreSQL connection string |
| `CONCERTO_HEARTBEAT_TIMEOUT_SEC` | `15` | Seconds before marking an agent stale |
| `CONCERTO_HEARTBEAT_CHECK_INTERVAL_SEC` | `5` | Heartbeat check frequency |
| `CONCERTO_WS_HOST` | `0.0.0.0` | Server bind host |
| `CONCERTO_WS_PORT` | `8000` | Server bind port |

### Agent

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_AGENT_NAME` | `testbed-01` | Agent display name |
| `AGENT_CAPABILITIES` | `["vehicle_gateway","asset_gateway"]` | Supported product types |
| `AGENT_CONTROLLER_URL` | `ws://localhost:8000/ws/agent` | Controller WebSocket URL |
| `AGENT_HEARTBEAT_INTERVAL_SEC` | `5` | Heartbeat interval in seconds |
| `AGENT_RECONNECT_BASE_DELAY_SEC` | `1.0` | Initial reconnect backoff |
| `AGENT_RECONNECT_MAX_DELAY_SEC` | `30.0` | Maximum reconnect backoff |

### MCP Server

| Variable | Default | Description |
|----------|---------|-------------|
| `CONCERTO_CONTROLLER_URL` | `http://localhost:8000` | Controller REST API base URL |

## Development

### Running Tests

```bash
# Unit tests with coverage
uv run pytest -v

# Or via tox
tox -e pytest
```

### Integration Tests

```bash
docker compose -f docker/docker-compose.integration.yml up --build --abort-on-container-exit
```

### Linting & Formatting

```bash
# Check all
tox -e black_checker -e isort_checker -e flake8 -e pylint -e docformatter_checker

# Auto-fix
tox -e black -e isort -e docformatter
```

### Database Migrations

```bash
# Apply migrations
uv run concerto-controller db migrate

# Generate a new migration
uv run concerto-controller db revision -m "add new column"

# Rollback one migration
uv run concerto-controller db downgrade
```

## CI/CD

Two GitHub Actions workflows run on every push to `main`:

- **CI** (`ci.yml`) — runs pytest with coverage (uploaded to Codecov), black, isort, flake8, pylint, and docformatter checks.
- **Integration** (`integration.yml`) — spins up PostgreSQL + test runner in Docker Compose, runs the integration test suite, and uploads JUnit XML results as artifacts.

## License

See [LICENSE](LICENSE) for details.
