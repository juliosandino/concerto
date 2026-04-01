"""MCP server for the Concerto controller — exposes REST API endpoints as MCP tools."""

from __future__ import annotations

import httpx
from concerto_shared.enums import AgentStatus, JobStatus, Product
from fastmcp import FastMCP
from loguru import logger


class ConcertoMCP:
    """Wraps a FastMCP server whose tools call the controller REST API via httpx."""

    def __init__(self, controller_url: str = "http://localhost:8000") -> None:
        self._base_url = controller_url.rstrip("/")
        self._mcp = FastMCP("Concerto Controller")
        self._register_tools()
        logger.info(f"ConcertoMCP initialized with controller URL: {self._base_url}")

    def _register_tools(self) -> None:
        """Register all MCP tools that map to controller REST endpoints."""

        base = self._base_url

        @self._mcp.tool()
        async def list_agents(status: AgentStatus | None = None) -> list[dict]:
            """List all registered agents.

            Returns each agent's id, name, status (online/busy/offline), capabilities list, current_job_id, and
            last_heartbeat timestamp.

            :param status: Optional filter — only return agents with this status (online, busy, or offline).
            """
            logger.info(f"list_agents called (status={status})")
            params: dict[str, str] = {}
            if status is not None:
                params["status"] = str(status)
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base}/agents", params=params, timeout=10)
                r.raise_for_status()
                agents = r.json()
                logger.info(f"list_agents returned {len(agents)} agents")
                return agents

        @self._mcp.tool()
        async def get_agent(agent_id: str) -> dict:
            """Get detailed information for a specific agent by its UUID.

            Returns the agent's id, name, status, capabilities, current_job_id, and last_heartbeat.

            :param agent_id: The UUID of the agent to retrieve.
            """
            logger.info(f"get_agent called (agent_id={agent_id})")
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base}/agents/{agent_id}", timeout=10)
                r.raise_for_status()
                logger.info(f"get_agent returned agent {agent_id}")
                return r.json()

        @self._mcp.tool()
        async def remove_agent(agent_id: str) -> str:
            """Remove an agent from the system.

            The agent's WebSocket connection is closed, any active jobs (ASSIGNED or RUNNING) are re-queued, and the
            agent record is deleted.

            :param agent_id: The UUID of the agent to remove.
            """
            logger.info(f"remove_agent called (agent_id={agent_id})")
            async with httpx.AsyncClient() as client:
                r = await client.delete(f"{base}/agents/{agent_id}", timeout=10)
                r.raise_for_status()
                logger.info(f"remove_agent removed agent {agent_id}")
                return f"Agent {agent_id} removed successfully"

        @self._mcp.tool()
        async def list_jobs(
            status: JobStatus | None = None,
            product: Product | None = None,
        ) -> list[dict]:
            """List all jobs, ordered by creation date (newest first).

            Returns each job's id, product, status, assigned_agent_id, created_at, started_at, completed_at, result, and
            duration.

            :param status: Optional filter — only return jobs with this status (queued, assigned, running, completed,
                  passed, or failed).
            :param product: Optional filter — only return jobs for this product (vehicle_gateway, asset_gateway,
                  environmental_monitor, or industrial_gateway).
            """
            logger.info(f"list_jobs called (status={status}, product={product})")
            params: dict[str, str] = {}
            if status is not None:
                params["status"] = str(status)
            if product is not None:
                params["product"] = str(product)
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base}/jobs", params=params, timeout=10)
                r.raise_for_status()
                jobs = r.json()
                logger.info(f"list_jobs returned {len(jobs)} jobs")
                return jobs

        @self._mcp.tool()
        async def get_job(job_id: str) -> dict:
            """Get detailed information for a specific job by its UUID.

            Returns the job's id, product, status, assigned_agent_id, created_at, started_at, completed_at, result, and
            duration.

            :param job_id: The UUID of the job to retrieve.
            """
            logger.info(f"get_job called (job_id={job_id})")
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{base}/jobs/{job_id}", timeout=10)
                r.raise_for_status()
                logger.info(f"get_job returned job {job_id}")
                return r.json()

        @self._mcp.tool()
        async def create_job(product: Product, duration: float | None = None) -> dict:
            """Queue a new test job for the specified product.

            The job is created with status 'queued' and the scheduler will automatically dispatch it to an available
            agent with the matching capability.

            :param product: The product to test (vehicle_gateway, asset_gateway, environmental_monitor, or
                  industrial_gateway).
            :param duration: Optional job duration in seconds. If omitted the agent will use its default execution time.
            """
            logger.info(f"create_job called (product={product}, duration={duration})")
            body: dict = {"product": str(product)}
            if duration is not None:
                body["duration"] = duration
            async with httpx.AsyncClient() as client:
                r = await client.post(f"{base}/jobs", json=body, timeout=10)
                r.raise_for_status()
                result = r.json()
                logger.info(f"create_job created job {result.get('id')}")
                return result

    def run(self) -> None:
        """Start the MCP server over stdio."""
        self._mcp.run(transport="stdio")
