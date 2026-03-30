"""Heartbeat monitor that detects stale agents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from concerto_controller.api.ws.connections import agent_connections
from concerto_controller.api.ws.notifier import notifies_dashboards
from concerto_controller.config import settings
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import async_session
from concerto_controller.scheduler.dispatcher import try_dispatch
from concerto_shared.enums import AgentStatus, JobStatus
from loguru import logger
from sqlalchemy import select


async def heartbeat_monitor() -> None:
    """Background task that detects stale agents and re-queues their jobs.

    Runs in a loop every HEARTBEAT_CHECK_INTERVAL_SEC seconds.
    """
    logger.info(
        f"Heartbeat monitor started "
        f"(timeout={settings.heartbeat_timeout_sec}s, "
        f"interval={settings.heartbeat_check_interval_sec}s)"
    )

    while True:
        try:
            await asyncio.sleep(settings.heartbeat_check_interval_sec)
            await _check_stale_agents()
        except asyncio.CancelledError:
            logger.info("Heartbeat monitor cancelled")
            break
        except Exception:
            logger.exception("Error in heartbeat monitor")


@notifies_dashboards
async def _check_stale_agents() -> None:
    """Find agents whose heartbeat has expired and handle them."""
    async with async_session() as session:
        if stale_agents := await _get_stale_agents(session):

            for agent in stale_agents:
                await _handle_stale_agent(session, agent)

            await session.commit()

            # Try dispatching re-queued jobs
            async with async_session() as dispatch_session:
                await try_dispatch(dispatch_session)


async def _get_stale_agents(session) -> list[AgentRecord]:
    """Fetch agents whose heartbeat has expired.

    :param session: AsyncSession for database access
    :return: List of AgentRecord objects with expired heartbeats
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.heartbeat_timeout_sec
    )
    stmt = (
        select(AgentRecord)
        .where(
            AgentRecord.status != AgentStatus.OFFLINE,
            AgentRecord.last_heartbeat < cutoff,
        )
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _handle_stale_agent(session, agent: AgentRecord) -> None:
    """Mark a stale agent offline, close its WS, and re-queue its job.

    :param session: AsyncSession for database access
    :param agent: AgentRecord to handle
    """
    logger.warning(
        f"Agent {agent.name} ({agent.id}) heartbeat expired "
        f"(last: {agent.last_heartbeat})"
    )

    await _close_agent_ws(agent.id)
    agent.status = AgentStatus.OFFLINE

    if agent.current_job_id:
        await _requeue_agent_job(session, agent)


async def _close_agent_ws(agent_id) -> None:
    """Close the WebSocket connection for an agent, if still open.

    :param agent_id: UUID of the agent whose WS to close
    """
    ws = agent_connections.pop(agent_id, None)
    if ws:
        try:
            await ws.close(code=4002, reason="Heartbeat timeout")
        except Exception:
            pass


async def _requeue_agent_job(session, agent: AgentRecord) -> None:
    """Re-queue the job assigned to a stale agent.

    :param session: AsyncSession for database access
    :param agent: AgentRecord whose current job should be re-queued
    """
    job = await session.get(JobRecord, agent.current_job_id)
    if job and job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING):
        logger.info(f"Re-queuing job {job.id} from stale agent {agent.id}")
        job.status = JobStatus.QUEUED
        job.assigned_agent_id = None
        job.started_at = None
    agent.current_job_id = None
