"""Dashboard WebSocket endpoint and command handlers."""

from __future__ import annotations

import uuid

from concerto_controller.connections import (
    agent_connections,
    dashboard_connections,
)
from concerto_controller.notifications import notifies_dashboards, notify_dashboards
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import async_session
from concerto_controller.scheduler.dispatcher import try_dispatch
from concerto_shared.enums import JobStatus, Product
from concerto_shared.messages import (
    DashboardCreateJobMessage,
    DashboardRemoveAgentMessage,
    DisconnectMessage,
    parse_dashboard_message,
)
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select

router = APIRouter()


@router.websocket("/ws/dashboard")
async def dashboard_websocket(ws: WebSocket) -> None:
    """Handle dashboard WebSocket connections.

    :param ws: WebSocket connection to the dashboard client
    """
    await ws.accept()
    dashboard_connections.add(ws)
    logger.info("Dashboard client connected")

    try:
        # Send initial snapshot
        await notify_dashboards()

        # Listen for commands
        while True:
            raw = await ws.receive_text()
            msg = parse_dashboard_message(raw)

            match msg:
                case DashboardRemoveAgentMessage():
                    await _handle_remove_agent(msg.agent_id)
                case DashboardCreateJobMessage():
                    await _handle_create_job(msg.product, msg.duration)

    except WebSocketDisconnect:
        logger.info("Dashboard client disconnected")
    except Exception:
        logger.exception("Error in dashboard WebSocket")
    finally:
        dashboard_connections.discard(ws)


@notifies_dashboards
async def _handle_remove_agent(agent_id: uuid.UUID) -> None:
    """Remove an agent (same logic as the REST DELETE endpoint).

    :param agent_id: UUID of the agent to remove
    """
    async with async_session() as session:
        result = await session.execute(
            select(AgentRecord).where(AgentRecord.id == agent_id).with_for_update()
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return

        ws = agent_connections.pop(agent_id, None)
        if ws:
            try:
                msg = DisconnectMessage(reason="Removed by controller")
                await ws.send_text(msg.model_dump_json())
                await ws.close(code=1000, reason="Agent removed")
            except Exception:
                pass

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


async def _handle_create_job(product: Product, duration: float | None) -> None:
    """Create a job (same logic as the REST POST endpoint).

    :param product: Product for the new job
    :param duration: Optional duration for the new job
    """
    async with async_session() as session:
        job = JobRecord(
            id=uuid.uuid4(),
            product=product,
            status=JobStatus.QUEUED,
            duration=duration,
        )
        session.add(job)
        await session.commit()

        await try_dispatch(session)
