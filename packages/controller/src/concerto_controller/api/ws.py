from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from concerto_shared.enums import AgentStatus, JobStatus
from concerto_shared.messages import (
    HeartbeatMessage,
    JobStatusMessage,
    MessageType,
    RegisterMessage,
    parse_message,
)
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import async_session

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory map of connected agents: agent_id → WebSocket
connections: dict[uuid.UUID, WebSocket] = {}


@router.websocket("/ws/agent")
async def agent_websocket(ws: WebSocket) -> None:
    await ws.accept()
    agent_id: uuid.UUID | None = None

    try:
        # First message must be a RegisterMessage
        raw = await ws.receive_text()
        msg = parse_message(raw)
        if not isinstance(msg, RegisterMessage):
            await ws.close(code=4001, reason="First message must be register")
            return

        agent_id = msg.agent_id
        now = datetime.now(timezone.utc)

        async with async_session() as session:
            # Upsert agent record
            agent = await session.get(AgentRecord, agent_id)
            if agent:
                agent.name = msg.agent_name
                agent.capabilities = [str(c) for c in msg.capabilities]
                agent.status = AgentStatus.ONLINE
                agent.last_heartbeat = now
            else:
                agent = AgentRecord(
                    id=agent_id,
                    name=msg.agent_name,
                    capabilities=[str(c) for c in msg.capabilities],
                    status=AgentStatus.ONLINE,
                    last_heartbeat=now,
                )
                session.add(agent)
            await session.commit()

        connections[agent_id] = ws
        logger.info("Agent %s (%s) registered with capabilities %s", msg.agent_name, agent_id, msg.capabilities)

        # Trigger dispatcher for any queued jobs
        async with async_session() as session:
            from concerto_controller.scheduler.dispatcher import try_dispatch

            await try_dispatch(session)

        # Main message loop
        while True:
            raw = await ws.receive_text()
            msg = parse_message(raw)

            if isinstance(msg, HeartbeatMessage):
                async with async_session() as session:
                    agent = await session.get(AgentRecord, agent_id)
                    if agent:
                        agent.last_heartbeat = datetime.now(timezone.utc)
                        await session.commit()

            elif isinstance(msg, JobStatusMessage):
                await _handle_job_status(msg)

    except WebSocketDisconnect:
        logger.info("Agent %s disconnected", agent_id)
    except Exception:
        logger.exception("Error in agent WebSocket for %s", agent_id)
    finally:
        if agent_id:
            connections.pop(agent_id, None)
            await _handle_agent_disconnect(agent_id)


async def _handle_job_status(msg: JobStatusMessage) -> None:
    """Process a job status update from an agent."""
    async with async_session() as session:
        job = await session.get(JobRecord, msg.job_id)
        if not job:
            logger.warning("Job status update for unknown job %s", msg.job_id)
            return

        now = datetime.now(timezone.utc)

        if msg.status == JobStatus.RUNNING:
            job.status = JobStatus.RUNNING
            job.started_at = now
        elif msg.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            job.status = msg.status
            job.completed_at = now
            job.result = msg.result
            job.assigned_agent_id = None

            # Free the agent
            agent = await session.get(AgentRecord, msg.agent_id)
            if agent:
                agent.status = AgentStatus.ONLINE
                agent.current_job_id = None

        await session.commit()

        # If job finished, try dispatching queued jobs
        if msg.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            from concerto_controller.scheduler.dispatcher import try_dispatch

            await try_dispatch(session)


async def _handle_agent_disconnect(agent_id: uuid.UUID) -> None:
    """Mark agent offline and re-queue any assigned/running job."""
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
                logger.info("Re-queuing job %s from disconnected agent %s", job.id, agent_id)
                job.status = JobStatus.QUEUED
                job.assigned_agent_id = None
                job.started_at = None
            agent.current_job_id = None

        await session.commit()

        # Try to dispatch re-queued jobs
        from concerto_controller.scheduler.dispatcher import try_dispatch

        await try_dispatch(session)
