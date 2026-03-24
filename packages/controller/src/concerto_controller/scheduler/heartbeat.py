from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from concerto_controller.config import settings
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.db.session import async_session
from concerto_controller.scheduler.dispatcher import try_dispatch
from loguru import logger
from concerto_shared.enums import AgentStatus, JobStatus
from sqlalchemy import select


async def heartbeat_monitor() -> None:
    """Background task that detects stale agents and re-queues their jobs.

    Runs in a loop every HEARTBEAT_CHECK_INTERVAL_SEC seconds.
    """
    logger.info(f"Heartbeat monitor started (timeout={settings.heartbeat_timeout_sec}s, interval={settings.heartbeat_check_interval_sec}s)")

    while True:
        try:
            await asyncio.sleep(settings.heartbeat_check_interval_sec)
            await _check_stale_agents()
        except asyncio.CancelledError:
            logger.info("Heartbeat monitor cancelled")
            break
        except Exception:
            logger.exception("Error in heartbeat monitor")


async def _check_stale_agents() -> None:
    """Find agents whose heartbeat has expired and handle them."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.heartbeat_timeout_sec
    )

    async with async_session() as session:
        stmt = (
            select(AgentRecord)
            .where(
                AgentRecord.status != AgentStatus.OFFLINE,
                AgentRecord.last_heartbeat < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        stale_agents = list(result.scalars().all())

        if not stale_agents:
            return

        for agent in stale_agents:
            logger.warning(f"Agent {agent.name} ({agent.id}) heartbeat expired (last: {agent.last_heartbeat}, cutoff: {cutoff})")

            # Close the WebSocket if still connected
            from concerto_controller.api.ws import connections

            ws = connections.pop(agent.id, None)
            if ws:
                try:
                    await ws.close(code=4002, reason="Heartbeat timeout")
                except Exception:
                    pass

            agent.status = AgentStatus.OFFLINE

            # Re-queue any assigned/running job
            if agent.current_job_id:
                job = await session.get(JobRecord, agent.current_job_id)
                if job and job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING):
                    logger.info(f"Re-queuing job {job.id} from stale agent {agent.id}")
                    job.status = JobStatus.QUEUED
                    job.assigned_agent_id = None
                    job.started_at = None
                agent.current_job_id = None

        await session.commit()

        # Try dispatching re-queued jobs
        async with async_session() as dispatch_session:
            await try_dispatch(dispatch_session)
