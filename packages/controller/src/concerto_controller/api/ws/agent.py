"""Agent WebSocket endpoint and message handlers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from concerto_controller.api.ws.connections import agent_connections
from concerto_controller.api.ws.notifier import notifies_dashboards
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import async_session
from concerto_controller.scheduler.dispatcher import try_dispatch
from concerto_shared.enums import AgentStatus, JobStatus
from concerto_shared.messages import (
    HeartbeatMessage,
    JobStatusMessage,
    RegisterAckMessage,
    RegisterMessage,
    parse_message,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_websocket(ws: WebSocket) -> None:
    """Handle agent WebSocket connections."""
    await ws.accept()
    agent_id: uuid.UUID | None = None

    try:
        # First message must be a RegisterMessage
        raw = await ws.receive_text()
        msg = parse_message(raw)
        if not isinstance(msg, RegisterMessage):
            await ws.close(code=4001, reason="First message must be register")
            return

        async with async_session() as session:
            agent_id = await _register_agent(ws, session, msg)
            if agent_id is None:
                return

        # Main message loop
        while True:
            raw = await ws.receive_text()
            msg = parse_message(raw)

            match msg:
                case HeartbeatMessage():
                    async with async_session() as session:
                        agent = await session.get(AgentRecord, agent_id)
                        if agent:
                            agent.last_heartbeat = datetime.now(timezone.utc)
                            await session.commit()
                case JobStatusMessage():
                    await _handle_job_status(msg)

    except WebSocketDisconnect:
        logger.info(f"Agent {agent_id} disconnected")
    except Exception:
        logger.exception(f"Error in agent WebSocket for {agent_id}")
    finally:
        if agent_id:
            # Only run disconnect logic if we still owned the connection.
            # When the DELETE handler removes an agent it pops the connection
            # first, so this pop returns None and we skip the redundant (and
            # potentially conflicting) disconnect handler.
            was_tracked = agent_connections.pop(agent_id, None) is not None
            if was_tracked:
                await _handle_agent_disconnect(agent_id)


@notifies_dashboards
async def _register_agent(
    ws: WebSocket,
    session: AsyncSession,
    msg: RegisterMessage,
) -> uuid.UUID | None:
    """Look up or create an agent record and return its ID.

    Returns ``None`` if the agent name is already connected (the WS is
    closed with a 4002 code in that case).
    :param ws: WebSocket connection to the agent
    :param session: AsyncSession for database access
    :param msg: RegisterMessage received from the agent
    :return: UUID of the registered agent, or None if registration failed
    """
    result = await session.execute(
        select(AgentRecord).where(AgentRecord.name == msg.agent_name)
    )
    agent = result.scalar_one_or_none()

    # If an agent with this name already exists and is connected, reject the registration
    if agent and agent.id in agent_connections:
        await ws.close(
            code=4002,
            reason=f"Agent with name '{msg.agent_name}' is already connected",
        )
        return None

    # If the agent exists but isn't connected, update its record; otherwise create a new one
    now = datetime.now(timezone.utc)
    if agent:
        agent_id = agent.id
        agent.capabilities = [str(c) for c in msg.capabilities]
        agent.status = AgentStatus.ONLINE
        agent.last_heartbeat = now
    else:
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name=msg.agent_name,
            capabilities=[str(c) for c in msg.capabilities],
            status=AgentStatus.ONLINE,
            last_heartbeat=now,
        )
        session.add(agent)
    await session.commit()

    # Send the server-assigned ID back to the agent
    ack = RegisterAckMessage(agent_id=agent_id)
    await ws.send_text(ack.model_dump_json())

    agent_connections[agent_id] = ws
    logger.info(
        f"Agent {msg.agent_name} ({agent_id}) registered with capabilities {msg.capabilities}"
    )
    await try_dispatch(session)
    return agent_id


@notifies_dashboards
async def _handle_job_status(msg: JobStatusMessage) -> None:
    """Process a job status update from an agent.

    :param msg: JobStatusMessage received from the agent
    """
    async with async_session() as session:
        job = await session.get(JobRecord, msg.job_id)
        if not job:
            logger.warning(f"Job status update for unknown job {msg.job_id}")
            return

        now = datetime.now(timezone.utc)

        if msg.status == JobStatus.RUNNING:
            job.status = JobStatus.RUNNING
            job.started_at = now
        elif msg.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PASSED):
            job.status = msg.status
            job.completed_at = now
            job.result = msg.result

            # Free the agent
            agent = await session.get(AgentRecord, msg.agent_id)
            if agent:
                agent.status = AgentStatus.ONLINE
                agent.current_job_id = None

        await session.commit()

        # If job finished, try dispatching queued jobs
        if msg.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PASSED):
            from concerto_controller.scheduler.dispatcher import try_dispatch

            await try_dispatch(session)


@notifies_dashboards
async def _handle_agent_disconnect(agent_id: uuid.UUID) -> None:
    """Mark agent offline and re-queue any assigned/running job.

    :param agent_id: UUID of the disconnected agent
    """
    async with async_session() as session:
        agent = await session.get(AgentRecord, agent_id)
        if not agent:
            return

        agent.status = AgentStatus.OFFLINE
        agent.last_heartbeat = None

        # Re-queue any job this agent was working on
        if agent.current_job_id:
            job = await session.get(JobRecord, agent.current_job_id)
            if job and job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING):
                logger.info(
                    f"Re-queuing job {job.id} from disconnected agent {agent_id}"
                )
                job.status = JobStatus.QUEUED
                job.assigned_agent_id = None
                job.started_at = None
            agent.current_job_id = None

        await session.commit()

        # Try to dispatch re-queued jobs
        from concerto_controller.scheduler.dispatcher import try_dispatch

        await try_dispatch(session)
