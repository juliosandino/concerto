"""Tests for the agents REST API endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from concerto_controller.api.agents import (
    _to_info,
    get_agent,
    list_agents,
    remove_agent,
)
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_shared.enums import AgentStatus, JobStatus, Product


def _make_agent(agent_id=None, name="a1", status=AgentStatus.ONLINE, caps=None):
    return AgentRecord(
        id=agent_id or uuid.uuid4(),
        name=name,
        capabilities=caps or ["vehicle_gateway"],
        status=status,
        last_heartbeat=datetime.now(timezone.utc),
    )


class TestListAgents:
    """Tests for the list_agents endpoint."""

    @pytest.mark.asyncio
    async def test_returns_all_agents(self):
        """Verify list_agents returns all agents when no filter."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [agent]
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        result = await list_agents(status=None, session=session)
        assert len(result) == 1
        assert result[0].name == "a1"

    @pytest.mark.asyncio
    async def test_filters_by_status(self):
        """Verify list_agents applies status filter."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=mock_result)

        result = await list_agents(status=AgentStatus.OFFLINE, session=session)
        assert result == []
        session.execute.assert_awaited_once()


class TestGetAgent:
    """Tests for the get_agent endpoint."""

    @pytest.mark.asyncio
    async def test_returns_agent(self):
        """Verify get_agent returns an agent by ID."""
        agent = _make_agent()
        session = AsyncMock()
        session.get = AsyncMock(return_value=agent)

        result = await get_agent(agent_id=agent.id, session=session)
        assert result.id == agent.id

    @pytest.mark.asyncio
    async def test_404_when_not_found(self):
        """Verify get_agent raises 404 when agent doesn't exist."""
        from fastapi import HTTPException

        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_agent(agent_id=uuid.uuid4(), session=session)
        assert exc_info.value.status_code == 404


class TestRemoveAgent:
    """Tests for the remove_agent endpoint."""

    @pytest.mark.asyncio
    async def test_removes_agent_no_ws(self):
        """Verify remove_agent deletes agent with no active WS."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = agent

        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[mock_result, jobs_result])
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch("concerto_controller.api.ws.connections", {}),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await remove_agent(agent_id=agent.id, session=session)

        session.delete.assert_awaited_once_with(agent)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_removes_agent_with_ws(self):
        """Verify remove_agent sends disconnect and closes WS."""
        agent_id = uuid.uuid4()
        agent = _make_agent(agent_id=agent_id)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = agent

        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[mock_result, jobs_result])
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        mock_ws = AsyncMock()
        connections = {agent_id: mock_ws}

        with (
            patch("concerto_controller.api.ws.connections", connections),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await remove_agent(agent_id=agent_id, session=session)

        mock_ws.send_text.assert_awaited_once()
        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_removes_agent_ws_exception_suppressed(self):
        """Verify WS exception during removal is suppressed."""
        agent_id = uuid.uuid4()
        agent = _make_agent(agent_id=agent_id)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = agent

        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = []

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[mock_result, jobs_result])
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock(side_effect=Exception("gone"))
        connections = {agent_id: mock_ws}

        with (
            patch("concerto_controller.api.ws.connections", connections),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await remove_agent(agent_id=agent_id, session=session)  # should not raise

        session.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_404_when_agent_not_found(self):
        """Verify remove_agent raises 404 when agent doesn't exist."""
        from fastapi import HTTPException

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await remove_agent(agent_id=uuid.uuid4(), session=session)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_requeues_active_jobs_and_clears_finished(self):
        """Verify active jobs are requeued and finished jobs have agent_id cleared."""
        agent_id = uuid.uuid4()
        agent = _make_agent(agent_id=agent_id)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = agent

        running_job = JobRecord(
            id=uuid.uuid4(),
            product="vehicle_gateway",
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )
        completed_job = JobRecord(
            id=uuid.uuid4(),
            product="vehicle_gateway",
            status=JobStatus.COMPLETED,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )

        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [running_job, completed_job]

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[mock_result, jobs_result])
        session.delete = AsyncMock()
        session.commit = AsyncMock()

        with (
            patch("concerto_controller.api.ws.connections", {}),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.dashboard_ws.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await remove_agent(agent_id=agent_id, session=session)

        assert running_job.status == JobStatus.QUEUED
        assert running_job.assigned_agent_id is None
        assert completed_job.status == JobStatus.COMPLETED
        assert completed_job.assigned_agent_id is None


class TestToInfo:
    """Tests for the _to_info helper."""

    def test_converts_agent_record(self):
        """Verify _to_info converts AgentRecord to AgentInfo."""
        agent = _make_agent(caps=["vehicle_gateway", "asset_gateway"])
        info = _to_info(agent)
        assert info.id == agent.id
        assert info.name == agent.name
        assert info.capabilities == [Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY]
        assert info.status == agent.status
