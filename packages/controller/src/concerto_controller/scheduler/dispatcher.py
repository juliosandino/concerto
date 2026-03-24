"""Job dispatcher that matches queued jobs to available agents."""

from __future__ import annotations

import uuid

from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_shared.enums import AgentStatus, JobStatus
from concerto_shared.messages import JobAssignMessage
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def try_dispatch(session: AsyncSession) -> None:
    """Attempt to assign queued jobs to available compatible agents.

    Uses SELECT ... FOR UPDATE on both job and agent rows to prevent
    race conditions with concurrent dispatch attempts.
    """
    # Get all queued jobs ordered by creation time (FIFO)
    queued_stmt = (
        select(JobRecord)
        .where(JobRecord.status == JobStatus.QUEUED)
        .order_by(JobRecord.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(queued_stmt)
    queued_jobs = list(result.scalars().all())

    if not queued_jobs:
        return

    for job in queued_jobs:
        # Only consider agents that actually have an active WS connection
        from concerto_controller.api.ws import connections

        connected_ids = list(connections.keys())
        if not connected_ids:
            logger.debug(f"No connected agents for job {job.id}")
            continue

        # Find an online, connected agent that supports this product
        agent_stmt = (
            select(AgentRecord)
            .where(
                AgentRecord.status == AgentStatus.ONLINE,
                AgentRecord.id.in_(connected_ids),
                AgentRecord.capabilities.any(str(job.product)),
            )
            .order_by(AgentRecord.last_heartbeat.asc())  # least-recently-active first
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        agent_result = await session.execute(agent_stmt)
        agent = agent_result.scalar_one_or_none()

        if not agent:
            logger.debug(f"No available agent for job {job.id} (product={job.product})")
            continue

        # Assign the job
        job.status = JobStatus.ASSIGNED
        job.assigned_agent_id = agent.id
        agent.status = AgentStatus.BUSY
        agent.current_job_id = job.id

        await session.commit()

        logger.info(f"Dispatched job {job.id} → agent {agent.name} ({agent.id})")

        # Send assignment over WebSocket; undo if delivery fails
        if not await _send_job_assignment(agent.id, job):
            job.status = JobStatus.QUEUED
            job.assigned_agent_id = None
            job.started_at = None
            agent.status = AgentStatus.ONLINE
            agent.current_job_id = None
            await session.commit()
            logger.warning(
                f"Reverted dispatch of job {job.id} — agent {agent.name} unreachable"
            )

    # Notify dashboards of dispatch changes
    from concerto_controller.api.dashboard_ws import notify_dashboards

    await notify_dashboards()


async def _send_job_assignment(agent_id: uuid.UUID, job: JobRecord) -> bool:
    """Send a JobAssignMessage to the agent over its WebSocket connection.

    Returns True if the message was delivered, False otherwise.
    """
    from concerto_controller.api.ws import connections

    ws = connections.get(agent_id)
    if not ws:
        logger.warning(
            f"No WebSocket connection for agent {agent_id} to send job assignment"
        )
        return False

    msg = JobAssignMessage(job_id=job.id, product=job.product, duration=job.duration)
    try:
        await ws.send_text(msg.model_dump_json())
        return True
    except Exception:
        logger.exception(f"Failed to send job assignment to agent {agent_id}")
        return False
