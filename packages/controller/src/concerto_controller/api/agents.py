from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from concerto_shared.enums import AgentStatus
from concerto_shared.models import AgentInfo
from concerto_controller.db.models import AgentRecord
from concerto_controller.db.session import get_session

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
