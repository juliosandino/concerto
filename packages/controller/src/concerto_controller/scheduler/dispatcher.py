from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from concerto_shared.enums import AgentStatus, JobStatus
from concerto_shared.messages import JobAssignMessage
from concerto_controller.db.models import AgentRecord, JobRecord

logger = logging.getLogger(__name__)


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
        # Find an online agent that supports this product
        agent_stmt = (
            select(AgentRecord)
            .where(
                AgentRecord.status == AgentStatus.ONLINE,
                AgentRecord.capabilities.any(str(job.product)),
            )
            .order_by(AgentRecord.last_heartbeat.asc())  # least-recently-active first
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        agent_result = await session.execute(agent_stmt)
        agent = agent_result.scalar_one_or_none()

        if not agent:
            logger.debug("No available agent for job %s (product=%s)", job.id, job.product)
            continue

        # Assign the job
        job.status = JobStatus.ASSIGNED
        job.assigned_agent_id = agent.id
        agent.status = AgentStatus.BUSY
        agent.current_job_id = job.id

        await session.commit()

        logger.info("Dispatched job %s → agent %s (%s)", job.id, agent.name, agent.id)

        # Send assignment over WebSocket
        await _send_job_assignment(agent.id, job)


async def _send_job_assignment(agent_id: uuid.UUID, job: JobRecord) -> None:
    """Send a JobAssignMessage to the agent over its WebSocket connection."""
    from concerto_controller.api.ws import connections

    ws = connections.get(agent_id)
    if not ws:
        logger.warning("No WebSocket connection for agent %s to send job assignment", agent_id)
        return

    msg = JobAssignMessage(job_id=job.id, product=job.product)
    try:
        await ws.send_text(msg.model_dump_json())
    except Exception:
        logger.exception("Failed to send job assignment to agent %s", agent_id)
