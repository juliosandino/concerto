from __future__ import annotations

import uuid

from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import get_session
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
    return [_to_info(a) for a in result.scalars().all()]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AgentInfo:
    """Get a specific agent by ID."""
    agent = await session.get(AgentRecord, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _to_info(agent)


@router.delete("/{agent_id}", status_code=204)
async def remove_agent(
    agent_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove an agent. If online, sends a disconnect and closes the WS."""
    agent = await session.get(AgentRecord, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # If the agent has an active WS connection, tell it to terminate
    from concerto_controller.api.ws import connections

    ws = connections.pop(agent_id, None)
    if ws:
        try:
            msg = DisconnectMessage(reason="Removed by controller")
            await ws.send_text(msg.model_dump_json())
            await ws.close(code=1000, reason="Agent removed")
        except Exception:
            pass  # best-effort; agent may already be gone

    # Re-queue any job the agent was working on
    if agent.current_job_id:
        job = await session.get(JobRecord, agent.current_job_id)
        if job and job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING):
            job.status = JobStatus.QUEUED
            job.assigned_agent_id = None
            job.started_at = None

    await session.delete(agent)
    await session.commit()

    # Try to dispatch any re-queued jobs
    from concerto_controller.scheduler.dispatcher import try_dispatch

    await try_dispatch(session)

    # Notify dashboards
    from concerto_controller.api.dashboard_ws import notify_dashboards

    await notify_dashboards()


def _to_info(agent: AgentRecord) -> AgentInfo:
    from concerto_shared.enums import Product

    return AgentInfo(
        id=agent.id,
        name=agent.name,
        capabilities=[Product(c) for c in agent.capabilities],
        status=agent.status,
        current_job_id=agent.current_job_id,
        last_heartbeat=agent.last_heartbeat,
    )
