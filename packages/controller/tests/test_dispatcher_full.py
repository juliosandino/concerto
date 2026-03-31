"""Tests for the job dispatcher."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_controller.scheduler.dispatcher import _send_job_assignment, try_dispatch
from concerto_shared.enums import AgentStatus, JobStatus, Product


def _make_agent(agent_id=None, name="a1", status=AgentStatus.ONLINE, caps=None):
    return AgentRecord(
        id=agent_id or uuid.uuid4(),
        name=name,
        capabilities=caps or ["vehicle_gateway"],
        status=status,
        last_heartbeat=datetime.now(timezone.utc),
    )


def _make_job(job_id=None, product=Product.VEHICLE_GATEWAY, status=JobStatus.QUEUED):
    return JobRecord(
        id=job_id or uuid.uuid4(),
        product=product,
        status=status,
        created_at=datetime.now(timezone.utc),
    )


class TestTryDispatchNoJobs:
    """Test try_dispatch when there are no queued jobs."""

    @pytest.mark.asyncio
    async def test_returns_early_when_no_queued_jobs(self):
        """Verify try_dispatch returns immediately if no jobs are queued."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        with patch(
            "concerto_controller.notifications.notify_dashboards",
            new_callable=AsyncMock,
        ):
            await try_dispatch(session)

        session.commit.assert_not_awaited()


class TestTryDispatchNoConnectedAgents:
    """Test try_dispatch when no agents are connected."""

    @pytest.mark.asyncio
    async def test_skips_when_no_connected_agents(self):
        """Verify try_dispatch skips assignment when no agents are connected."""
        job = _make_job()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [job]

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("concerto_controller.scheduler.dispatcher.agent_connections", {}),
            patch(
                "concerto_controller.notifications.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await try_dispatch(session)

        assert job.status == JobStatus.QUEUED


class TestTryDispatchNoMatchingAgent:
    """Test try_dispatch when no agent matches the job."""

    @pytest.mark.asyncio
    async def test_skips_when_no_matching_agent(self):
        """Verify try_dispatch skips when no compatible agent is found."""
        job = _make_job()
        agent_id = uuid.uuid4()

        queued_result = MagicMock()
        queued_result.scalars.return_value.all.return_value = [job]

        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[queued_result, agent_result])

        with (
            patch(
                "concerto_controller.scheduler.dispatcher.agent_connections",
                {agent_id: MagicMock()},
            ),
            patch(
                "concerto_controller.notifications.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await try_dispatch(session)

        assert job.status == JobStatus.QUEUED


class TestTryDispatchSuccess:
    """Test try_dispatch when a match is found and delivery succeeds."""

    @pytest.mark.asyncio
    async def test_assigns_job_to_agent(self):
        """Verify try_dispatch assigns the job and marks the agent busy."""
        agent_id = uuid.uuid4()
        agent = _make_agent(agent_id=agent_id)
        job = _make_job()

        queued_result = MagicMock()
        queued_result.scalars.return_value.all.return_value = [job]

        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = agent

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[queued_result, agent_result])
        session.commit = AsyncMock()

        mock_ws = AsyncMock()

        with (
            patch(
                "concerto_controller.scheduler.dispatcher.agent_connections",
                {agent_id: mock_ws},
            ),
            patch(
                "concerto_controller.scheduler.dispatcher._send_job_assignment",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "concerto_controller.notifications.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await try_dispatch(session)

        assert job.status == JobStatus.ASSIGNED
        assert job.assigned_agent_id == agent_id
        assert agent.status == AgentStatus.BUSY
        session.commit.assert_awaited()


class TestTryDispatchSendFailure:
    """Test try_dispatch when WS delivery fails (revert)."""

    @pytest.mark.asyncio
    async def test_reverts_on_send_failure(self):
        """Verify try_dispatch reverts assignment when send fails."""
        agent_id = uuid.uuid4()
        agent = _make_agent(agent_id=agent_id)
        job = _make_job()

        queued_result = MagicMock()
        queued_result.scalars.return_value.all.return_value = [job]

        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = agent

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[queued_result, agent_result])
        session.commit = AsyncMock()

        with (
            patch(
                "concerto_controller.scheduler.dispatcher.agent_connections",
                {agent_id: MagicMock()},
            ),
            patch(
                "concerto_controller.scheduler.dispatcher._send_job_assignment",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "concerto_controller.notifications.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await try_dispatch(session)

        # Should revert to queued
        assert job.status == JobStatus.QUEUED
        assert job.assigned_agent_id is None
        assert agent.status == AgentStatus.ONLINE
        assert agent.current_job_id is None


class TestSendJobAssignment:
    """Tests for _send_job_assignment."""

    @pytest.mark.asyncio
    async def test_sends_successfully(self):
        """Verify _send_job_assignment sends message and returns True."""
        agent_id = uuid.uuid4()
        job = _make_job()
        mock_ws = AsyncMock()

        with patch(
            "concerto_controller.scheduler.dispatcher.agent_connections",
            {agent_id: mock_ws},
        ):
            result = await _send_job_assignment(agent_id, job)

        assert result is True
        mock_ws.send_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_connection(self):
        """Verify _send_job_assignment returns False when no WS exists."""
        agent_id = uuid.uuid4()
        job = _make_job()

        with patch("concerto_controller.scheduler.dispatcher.agent_connections", {}):
            result = await _send_job_assignment(agent_id, job)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_send_exception(self):
        """Verify _send_job_assignment returns False when send raises."""
        agent_id = uuid.uuid4()
        job = _make_job()
        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock(side_effect=Exception("broken"))

        with patch(
            "concerto_controller.scheduler.dispatcher.agent_connections",
            {agent_id: mock_ws},
        ):
            result = await _send_job_assignment(agent_id, job)

        assert result is False
