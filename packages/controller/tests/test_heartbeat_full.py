"""Tests for the heartbeat monitor."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.scheduler.heartbeat import (
    _check_stale_agents,
    heartbeat_monitor,
)
from concerto_shared.enums import AgentStatus, JobStatus, Product


class TestHeartbeatMonitor:
    """Tests for the heartbeat_monitor loop."""

    @pytest.mark.asyncio
    async def test_runs_and_cancels_cleanly(self):
        """Verify the monitor loop runs and handles CancelledError."""
        call_count = 0

        async def fake_check():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with (
            patch(
                "concerto_controller.scheduler.heartbeat._check_stale_agents",
                side_effect=fake_check,
            ),
            patch(
                "concerto_controller.scheduler.heartbeat.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            await heartbeat_monitor()

        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self):
        """Verify the monitor continues after unexpected exceptions."""
        call_count = 0

        async def fake_check():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")
            raise asyncio.CancelledError()

        with (
            patch(
                "concerto_controller.scheduler.heartbeat._check_stale_agents",
                side_effect=fake_check,
            ),
            patch(
                "concerto_controller.scheduler.heartbeat.asyncio.sleep",
                new_callable=AsyncMock,
            ),
        ):
            await heartbeat_monitor()

        assert call_count >= 2


class TestCheckStaleAgents:
    """Tests for _check_stale_agents."""

    @pytest.mark.asyncio
    async def test_no_stale_agents(self):
        """Verify no action when no stale agents are found."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "concerto_controller.scheduler.heartbeat.async_session",
            return_value=mock_cm,
        ):
            await _check_stale_agents()

        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_marks_stale_agent_offline(self):
        """Verify stale agent is marked offline."""
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="stale",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=60),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_dispatch_session = AsyncMock()
        mock_dispatch_cm = AsyncMock()
        mock_dispatch_cm.__aenter__ = AsyncMock(return_value=mock_dispatch_session)
        mock_dispatch_cm.__aexit__ = AsyncMock(return_value=False)

        session_calls = [mock_cm, mock_dispatch_cm]

        with (
            patch(
                "concerto_controller.scheduler.heartbeat.async_session",
                side_effect=session_calls,
            ),
            patch("concerto_controller.api.ws.connections", {}),
            patch(
                "concerto_controller.scheduler.heartbeat.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _check_stale_agents()

        assert agent.status == AgentStatus.OFFLINE

    @pytest.mark.asyncio
    async def test_requeues_job_from_stale_agent(self):
        """Verify the stale agent's job is re-queued."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()

        agent = AgentRecord(
            id=agent_id,
            name="stale-busy",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            current_job_id=job_id,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        job = JobRecord(
            id=job_id,
            product=Product.VEHICLE_GATEWAY,
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=job)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_dispatch_session = AsyncMock()
        mock_dispatch_cm = AsyncMock()
        mock_dispatch_cm.__aenter__ = AsyncMock(return_value=mock_dispatch_session)
        mock_dispatch_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.scheduler.heartbeat.async_session",
                side_effect=[mock_cm, mock_dispatch_cm],
            ),
            patch("concerto_controller.api.ws.connections", {}),
            patch(
                "concerto_controller.scheduler.heartbeat.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _check_stale_agents()

        assert agent.status == AgentStatus.OFFLINE
        assert agent.current_job_id is None
        assert job.status == JobStatus.QUEUED
        assert job.assigned_agent_id is None

    @pytest.mark.asyncio
    async def test_closes_ws_of_stale_agent(self):
        """Verify the stale agent's WS is closed if still connected."""
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="stale-connected",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=60),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_dispatch_cm = AsyncMock()
        mock_dispatch_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_dispatch_cm.__aexit__ = AsyncMock(return_value=False)

        mock_ws = AsyncMock()
        connections = {agent_id: mock_ws}

        with (
            patch(
                "concerto_controller.scheduler.heartbeat.async_session",
                side_effect=[mock_cm, mock_dispatch_cm],
            ),
            patch("concerto_controller.api.ws.connections", connections),
            patch(
                "concerto_controller.scheduler.heartbeat.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _check_stale_agents()

        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ws_close_exception_is_suppressed(self):
        """Verify exception during WS close is suppressed."""
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="stale-bad-ws",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=60),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=None)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_dispatch_cm = AsyncMock()
        mock_dispatch_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_dispatch_cm.__aexit__ = AsyncMock(return_value=False)

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=Exception("already closed"))
        connections = {agent_id: mock_ws}

        with (
            patch(
                "concerto_controller.scheduler.heartbeat.async_session",
                side_effect=[mock_cm, mock_dispatch_cm],
            ),
            patch("concerto_controller.api.ws.connections", connections),
            patch(
                "concerto_controller.scheduler.heartbeat.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _check_stale_agents()  # should not raise

        assert agent.status == AgentStatus.OFFLINE

    @pytest.mark.asyncio
    async def test_stale_agent_with_completed_job_not_requeued(self):
        """Verify a completed job is not re-queued when agent goes stale."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="stale-done",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            current_job_id=job_id,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=60),
        )
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=job)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_dispatch_cm = AsyncMock()
        mock_dispatch_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_dispatch_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.scheduler.heartbeat.async_session",
                side_effect=[mock_cm, mock_dispatch_cm],
            ),
            patch("concerto_controller.api.ws.connections", {}),
            patch(
                "concerto_controller.scheduler.heartbeat.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _check_stale_agents()

        # Job should stay COMPLETED, not QUEUED
        assert job.status == JobStatus.COMPLETED
        assert agent.current_job_id is None
