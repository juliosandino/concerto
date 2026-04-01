"""Integration test: verify an agent registers with the controller and appears in the REST API."""

import os

# Set environment BEFORE importing any concerto modules so all module-level
# settings, engines, and session factories initialise with the correct values.
os.environ["CONCERTO_DATABASE_URL"] = (
    "postgresql+asyncpg://concerto:concerto@postgres:5432/concerto"
)
os.environ["CONCERTO_WS_HOST"] = "0.0.0.0"
os.environ["CONCERTO_WS_PORT"] = "8000"

import asyncio  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import uvicorn  # noqa: E402
from concerto_agent.agent import ConcertoAgent  # noqa: E402
from concerto_controller.app import app  # noqa: E402
from concerto_shared.enums import Product  # noqa: E402

CONTROLLER_HOST = "0.0.0.0"
CONTROLLER_PORT = 8000
CONTROLLER_URL = f"http://localhost:{CONTROLLER_PORT}"
WS_URL = f"ws://localhost:{CONTROLLER_PORT}/ws/agent"
MAX_WAIT_SEC = 30
POLL_INTERVAL_SEC = 1

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def fx_controller():
    """Start the controller as a background uvicorn server."""
    config = uvicorn.Config(
        app, host=CONTROLLER_HOST, port=CONTROLLER_PORT, log_level="info"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())

    # Poll until the server is accepting connections
    async with httpx.AsyncClient() as client:
        deadline = asyncio.get_event_loop().time() + MAX_WAIT_SEC
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(f"{CONTROLLER_URL}/health", timeout=2)
                if r.status_code == 200:
                    break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                pass
            await asyncio.sleep(POLL_INTERVAL_SEC)
        else:
            raise TimeoutError("Controller did not become healthy in time")

    yield server

    server.should_exit = True
    await task


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def fx_agent(fx_controller):
    """Start an agent that connects to the controller."""
    agent_inst = ConcertoAgent(
        agent_name="testbed-alpha",
        capabilities=[Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY],
        controller_url=WS_URL,
        heartbeat_interval=5.0,
    )
    task = asyncio.create_task(agent_inst.run())

    # Poll until the agent shows up as online
    async with httpx.AsyncClient() as client:
        deadline = asyncio.get_event_loop().time() + MAX_WAIT_SEC
        while asyncio.get_event_loop().time() < deadline:
            try:
                r = await client.get(f"{CONTROLLER_URL}/agents", timeout=2)
                if r.status_code == 200 and any(
                    a["status"] == "online" for a in r.json()
                ):
                    break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                pass
            await asyncio.sleep(POLL_INTERVAL_SEC)
        else:
            raise TimeoutError("Agent did not register in time")

    yield agent_inst

    await agent_inst.stop("test teardown")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_agent_registration(fx_agent):
    """Verify the agent appears in the REST API with correct details.

    :param fx_agent: Fixture that ensures the agent is running and registered before the test runs.
    """
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{CONTROLLER_URL}/agents", timeout=3)

    assert r.status_code == 200
    agents = r.json()

    online = [a for a in agents if a["status"] == "online"]
    assert len(online) >= 1

    registered = online[0]
    assert registered["name"] == "testbed-alpha"
    assert registered["status"] == "online"
    assert "vehicle_gateway" in registered["capabilities"]
    assert "asset_gateway" in registered["capabilities"]
    assert registered["current_job_id"] is None
