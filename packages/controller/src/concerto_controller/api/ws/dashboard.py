"""Dashboard WebSocket endpoint and command handlers."""

from __future__ import annotations

import functools
import uuid
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar

from concerto_controller.api.ws.connections import (
    agent_connections,
    dashboard_connections,
)
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import async_session
from concerto_shared.enums import JobStatus, Product
from concerto_shared.messages import (
    DashboardCreateJobMessage,
    DashboardRemoveAgentMessage,
    DashboardSnapshotMessage,
    DisconnectMessage,
    parse_dashboard_message,
)
from concerto_shared.models import AgentInfo, JobInfo
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger
from sqlalchemy import select

P = ParamSpec("P")
T = TypeVar("T")


def notifies_dashboards(
    fn: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Coroutine[Any, Any, T]]:
    """Decorator that calls :func:`notify_dashboards` after the wrapped async function."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        result = await fn(*args, **kwargs)
        await notify_dashboards()
        return result

    return wrapper


async def notify_dashboards() -> None:
    """Build a snapshot and push it to every connected dashboard."""
    if not dashboard_connections:
        return

    async with async_session() as session:
        agents_result = await session.execute(
            select(AgentRecord).order_by(AgentRecord.name)
        )
        agents = [
            AgentInfo.from_record(agent) for agent in agents_result.scalars().all()
        ]

        jobs_result = await session.execute(
            select(JobRecord).order_by(JobRecord.created_at.desc())
        )
        jobs = [JobInfo.from_record(job) for job in jobs_result.scalars().all()]

    snapshot = DashboardSnapshotMessage(agents=agents, jobs=jobs)
    payload = snapshot.model_dump_json()

    dead: list[WebSocket] = []
    for ws in dashboard_connections:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        dashboard_connections.discard(ws)


router = APIRouter()


@router.websocket("/ws/dashboard")
async def dashboard_websocket(ws: WebSocket) -> None:
    """Handle dashboard WebSocket connections."""
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
    """Remove an agent (same logic as the REST DELETE endpoint)."""
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

        from concerto_controller.scheduler.dispatcher import try_dispatch

        await try_dispatch(session)


@notifies_dashboards
async def _handle_create_job(product: Product, duration: float | None) -> None:
    """Create a job (same logic as the REST POST endpoint)."""
    async with async_session() as session:
        job = JobRecord(
            id=uuid.uuid4(),
            product=product,
            status=JobStatus.QUEUED,
            duration=duration,
        )
        session.add(job)
        await session.commit()

        from concerto_controller.scheduler.dispatcher import try_dispatch

        await try_dispatch(session)
