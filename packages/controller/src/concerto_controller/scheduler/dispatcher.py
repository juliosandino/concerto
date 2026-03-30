"""Job dispatcher that matches queued jobs to available agents."""

from __future__ import annotations

import uuid

from concerto_controller.api.dashboard_ws import notifies_dashboards
from concerto_controller.api.ws import connections
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_shared.enums import AgentStatus, JobStatus
from concerto_shared.messages import JobAssignMessage
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

MIN_JOB_DURATION = 5.0  # seconds, for simulation purposes


@notifies_dashboards
async def try_dispatch(session: AsyncSession) -> None:
    """Attempt to assign queued jobs to available compatible agents.

    Uses SELECT ... FOR UPDATE on both job and agent rows to prevent
    race conditions with concurrent dispatch attempts.
    """
    # Get all queued jobs ordered by creation time (FIFO)
    queued_jobs = await _get_queued_jobs(session)

    for job in queued_jobs:

        if agent := await _get_available_agent(session, job):
            await _assign_job(session, job, agent)


async def _get_queued_jobs(session: AsyncSession) -> list[JobRecord]:
    """Fetch all queued jobs ordered by creation time.

    :param session: AsyncSession for database access
    :return: List of JobRecord objects with status=QUEUED
    """
    result = await session.execute(
        select(JobRecord)
        .where(JobRecord.status == JobStatus.QUEUED)
        .order_by(JobRecord.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    return result.scalars().all() or []


async def _get_available_agent(
    session: AsyncSession, job: JobRecord
) -> AgentRecord | None:
    """Find an online, connected agent compatible with the given job.

    :param session: AsyncSession for database access
    :param job: JobRecord to find an agent for
    :return: A matching AgentRecord, or None if no agent is available
    """
    connected_ids = list(connections.keys())
    if not connected_ids:
        logger.debug(f"No connected agents for job {job.id}")
        return None

    agents_query = (
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
    agent_result = await session.execute(agents_query)
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        logger.debug(f"No available agent for job {job.id} (product={job.product})")
    return agent


async def _assign_job(
    session: AsyncSession, job: JobRecord, agent: AgentRecord
) -> None:
    """Assign a job to an agent and send the assignment over WebSocket.

    If WebSocket delivery fails the assignment is rolled back and both
    the job and agent are restored to their previous state.

    :param session: AsyncSession for database access
    :param job: JobRecord to assign
    :param agent: AgentRecord to receive the job
    """
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


async def _send_job_assignment(agent_id: uuid.UUID, job: JobRecord) -> bool:
    """Send a JobAssignMessage to the agent over its WebSocket connection.

    :param agent_id: UUID of the agent to send the message to
    :param job: JobRecord of the job being assigned (must have ID, product, and duration set)
    :return: True if the message was sent successfully, False otherwise
    """
    ws = connections.get(agent_id)
    if not ws:
        logger.warning(
            f"No WebSocket connection for agent {agent_id} to send job assignment"
        )
        return False

    if job.duration is None:
        logger.debug(f"Setting duration for job {job.id} to {MIN_JOB_DURATION} seconds")
        job.duration = MIN_JOB_DURATION

    msg = JobAssignMessage(job_id=job.id, product=job.product, duration=job.duration)
    try:
        await ws.send_text(msg.model_dump_json())
        return True
    except Exception:
        logger.exception(f"Failed to send job assignment to agent {agent_id}")
        return False
