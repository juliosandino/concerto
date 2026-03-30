"""REST API endpoints for agent management."""

from __future__ import annotations

import uuid

from concerto_controller.api.ws.connections import agent_connections
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import get_session
from concerto_controller.scheduler.dispatcher import try_dispatch
from concerto_shared.enums import AgentStatus, JobStatus
from concerto_shared.messages import DisconnectMessage
from concerto_shared.models import AgentInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def list_agents(
    status: AgentStatus | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[AgentInfo]:
    """List all registered agents, optionally filtered by status."""
    stmt = select(AgentRecord).order_by(AgentRecord.name)
    if status:
        stmt = stmt.where(AgentRecord.status == status)
    result = await session.execute(stmt)
    return [AgentInfo.from_record(a) for a in result.scalars().all()]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AgentInfo:
    """Get a specific agent by ID."""
    agent = await session.get(AgentRecord, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentInfo.from_record(agent)


@router.delete("/{agent_id}", status_code=204)
async def remove_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove an agent.

    If online, sends a disconnect and closes the WS.
    """
    result = await session.execute(
        select(AgentRecord).where(AgentRecord.id == agent_id).with_for_update()
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    ws = agent_connections.pop(agent_id, None)
    if ws:
        try:
            msg = DisconnectMessage(reason="Removed by controller")
            await ws.send_text(msg.model_dump_json())
            await ws.close(code=1000, reason="Agent removed")
        except Exception:
            pass  # best-effort; agent may already be gone

    # Re-queue active jobs and clear FK on finished jobs
    assigned_jobs = await session.execute(
        select(JobRecord).where(JobRecord.assigned_agent_id == agent_id)
    )
    for job in assigned_jobs.scalars().all():
        if job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING):
            job.status = JobStatus.QUEUED
            job.started_at = None
        job.assigned_agent_id = None

    await session.delete(agent)
    await session.commit()

    await try_dispatch(session)
