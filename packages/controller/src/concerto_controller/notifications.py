"""Handles notifications to dashboard clients when agents report status updates or disconnect."""

import functools
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar

from concerto_controller.connections import dashboard_connections
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import async_session
from concerto_shared.messages import DashboardSnapshotMessage
from concerto_shared.models import AgentInfo, JobInfo
from fastapi import WebSocket
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
    # we cast to list to create a snapshot of the set
    # since it may be modified during iteration if a connection is closed
    for ws in list(dashboard_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        dashboard_connections.discard(ws)
