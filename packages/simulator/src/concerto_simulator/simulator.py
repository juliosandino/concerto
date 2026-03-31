"""Simple fleet simulator — spawns agents and queues jobs via the controller."""

from __future__ import annotations

import asyncio
import random

import websockets
from concerto_shared.enums import JobStatus, Product
from concerto_shared.messages import (
    DashboardCreateJobMessage,
    DashboardSnapshotMessage,
    parse_dashboard_message,
)
from concerto_simulator.agents import AgentManager
from loguru import logger

ALL_PRODUCTS = list(Product)


async def _wait_for_snapshot(
    ws: websockets.ClientConnection,
) -> DashboardSnapshotMessage:
    """Read frames until we get a DashboardSnapshotMessage."""
    async for raw in ws:
        msg = parse_dashboard_message(raw)
        if isinstance(msg, DashboardSnapshotMessage):
            return msg
    raise ConnectionError("WebSocket closed before snapshot received")


async def _queue_jobs(
    ws: websockets.ClientConnection,
    num_jobs: int,
    interval: float,
) -> None:
    """Send DashboardCreateJobMessage for each job over the WebSocket."""
    for i in range(num_jobs):
        product = random.choice(ALL_PRODUCTS)
        msg = DashboardCreateJobMessage(product=product)
        await ws.send(msg.model_dump_json())
        logger.info(f"Queued job {i + 1}/{num_jobs} (product={product.value})")
        if i < num_jobs - 1:
            await asyncio.sleep(interval)

    logger.info("All jobs queued")


async def _wait_for_jobs_done(
    ws: websockets.ClientConnection,
    num_jobs: int,
) -> None:
    """Wait for snapshots until every submitted job has a terminal status.

    :param ws: The WebSocket connection to read snapshots from.
    :param num_jobs: The total number of jobs that were submitted.
    """
    terminal = {JobStatus.COMPLETED, JobStatus.PASSED, JobStatus.FAILED}

    while True:
        snapshot = await _wait_for_snapshot(ws)
        done = [j for j in snapshot.jobs if j.status in terminal]
        if len(done) >= num_jobs:
            passed = sum(1 for j in done if j.status == JobStatus.PASSED)
            failed = sum(1 for j in done if j.status == JobStatus.FAILED)
            logger.info(
                f"All {num_jobs} jobs finished — {passed} passed, {failed} failed"
            )
            return
        logger.info(f"Jobs progress: {len(done)}/{num_jobs} complete")


async def run_simulation(
    num_agents: int,
    num_jobs: int,
    controller_ws_url: str,
    dashboard_ws_url: str,
    job_interval: float,
) -> None:
    """Spawn *num_agents* real agents and queue *num_jobs* jobs."""
    logger.info(
        f"Starting simulation: {num_agents} agents, {num_jobs} jobs "
        f"(agent_ws={controller_ws_url}, dashboard_ws={dashboard_ws_url}, "
        f"interval={job_interval}s)"
    )

    async with websockets.connect(dashboard_ws_url) as ws:
        async with AgentManager(num_agents, controller_ws_url, ws) as manager:
            await _queue_jobs(ws, num_jobs, job_interval)
            await _wait_for_jobs_done(ws, num_jobs)

    logger.info("Simulation finished")
