"""Tests for the ConcertoMCP server tools."""

from __future__ import annotations

import httpx
import pytest
from concerto_mcp.server import ConcertoMCP


@pytest.fixture()
def mcp() -> ConcertoMCP:
    """Create a ConcertoMCP instance pointed at a fake base URL."""
    return ConcertoMCP("http://test-controller:8000")


async def _get_tool_fn(mcp: ConcertoMCP, name: str):
    """Retrieve the raw callable for a registered tool by name.

    :param mcp: The ConcertoMCP instance to extract the tool from.
    :param name: The registered tool name.
    """
    tool = await mcp._mcp.get_tool(name)  # pylint: disable=protected-access
    return tool.fn


# ── list_agents ──────────────────────────────────────────────────────


async def test_list_agents(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify list_agents returns all agents when called without filters.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = [{"id": "abc", "name": "a1", "status": "online"}]
    httpx_mock.add_response(url="http://test-controller:8000/agents", json=payload)

    fn = await _get_tool_fn(mcp, "list_agents")
    result = await fn()
    assert result == payload


async def test_list_agents_with_status(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify list_agents passes the status query parameter when provided.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = [{"id": "abc", "name": "a1", "status": "online"}]
    httpx_mock.add_response(json=payload)

    fn = await _get_tool_fn(mcp, "list_agents")
    result = await fn(status="online")
    assert result == payload

    request = httpx_mock.get_request()
    assert request.url.params["status"] == "online"


# ── get_agent ────────────────────────────────────────────────────────


async def test_get_agent(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify get_agent returns the correct agent by UUID.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = {"id": "abc", "name": "a1", "status": "online"}
    httpx_mock.add_response(url="http://test-controller:8000/agents/abc", json=payload)

    fn = await _get_tool_fn(mcp, "get_agent")
    result = await fn(agent_id="abc")
    assert result == payload


async def test_get_agent_not_found(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify get_agent raises HTTPStatusError for a 404 response.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    httpx_mock.add_response(
        url="http://test-controller:8000/agents/missing", status_code=404
    )

    fn = await _get_tool_fn(mcp, "get_agent")
    with pytest.raises(httpx.HTTPStatusError):
        await fn(agent_id="missing")


# ── remove_agent ─────────────────────────────────────────────────────


async def test_remove_agent(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify remove_agent sends a DELETE request and returns a success message.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    httpx_mock.add_response(
        url="http://test-controller:8000/agents/abc", method="DELETE", status_code=204
    )

    fn = await _get_tool_fn(mcp, "remove_agent")
    result = await fn(agent_id="abc")
    assert "abc" in result


# ── list_jobs ────────────────────────────────────────────────────────


async def test_list_jobs(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify list_jobs returns all jobs when called without filters.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = [{"id": "j1", "product": "vehicle_gateway", "status": "queued"}]
    httpx_mock.add_response(url="http://test-controller:8000/jobs", json=payload)

    fn = await _get_tool_fn(mcp, "list_jobs")
    result = await fn()
    assert result == payload


async def test_list_jobs_filtered(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify list_jobs passes status and product query parameters when provided.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = []
    httpx_mock.add_response(json=payload)

    fn = await _get_tool_fn(mcp, "list_jobs")
    result = await fn(status="running", product="asset_gateway")
    assert result == payload

    request = httpx_mock.get_request()
    assert request.url.params["status"] == "running"
    assert request.url.params["product"] == "asset_gateway"


# ── get_job ──────────────────────────────────────────────────────────


async def test_get_job(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify get_job returns the correct job by UUID.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = {"id": "j1", "product": "vehicle_gateway", "status": "queued"}
    httpx_mock.add_response(url="http://test-controller:8000/jobs/j1", json=payload)

    fn = await _get_tool_fn(mcp, "get_job")
    result = await fn(job_id="j1")
    assert result == payload


# ── create_job ───────────────────────────────────────────────────────


async def test_create_job(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify create_job sends a POST request and returns the created job.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = {"id": "j2", "product": "vehicle_gateway", "status": "queued"}
    httpx_mock.add_response(
        url="http://test-controller:8000/jobs",
        method="POST",
        json=payload,
        status_code=201,
    )

    fn = await _get_tool_fn(mcp, "create_job")
    result = await fn(product="vehicle_gateway")
    assert result == payload


async def test_create_job_with_duration(mcp: ConcertoMCP, httpx_mock) -> None:
    """Verify create_job includes duration in the request body when provided.

    :param mcp: ConcertoMCP fixture.
    :param httpx_mock: pytest-httpx mock fixture.
    """
    payload = {
        "id": "j3",
        "product": "asset_gateway",
        "status": "queued",
        "duration": 30.0,
    }
    httpx_mock.add_response(
        url="http://test-controller:8000/jobs",
        method="POST",
        json=payload,
        status_code=201,
    )

    fn = await _get_tool_fn(mcp, "create_job")
    result = await fn(product="asset_gateway", duration=30.0)
    assert result == payload
