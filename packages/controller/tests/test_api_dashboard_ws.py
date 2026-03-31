"""Tests for the dashboard WebSocket endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from concerto_controller.api.ws.dashboard import (
    _handle_create_job,
    _handle_remove_agent,
    dashboard_connections,
    dashboard_websocket,
    notify_dashboards,
)
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_shared.enums import AgentStatus, JobStatus, Product
from concerto_shared.messages import (
    DashboardCreateJobMessage,
    DashboardRemoveAgentMessage,
)
from fastapi import WebSocketDisconnect


class TestNotifyDashboards:
    """Tests for notify_dashboards."""

    @pytest.mark.asyncio
    async def test_noop_when_no_connections(self):
        """Verify notify_dashboards does nothing when no dashboards connected."""
        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        try:
            await notify_dashboards()
        finally:
            dashboard_connections.update(saved)

    @pytest.mark.asyncio
    async def test_sends_snapshot_to_dashboards(self):
        """Verify snapshots are sent to all connected dashboards."""
        agent = AgentRecord(
            id=uuid.uuid4(),
            name="a1",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )
        job = JobRecord(
            id=uuid.uuid4(),
            product="vehicle_gateway",
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [agent]
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [job]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[agents_result, jobs_result])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_ws = AsyncMock()

        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        dashboard_connections.add(mock_ws)
        try:
            with patch(
                "concerto_controller.notifications.async_session",
                return_value=mock_cm,
            ):
                await notify_dashboards()
            mock_ws.send_text.assert_awaited_once()
        finally:
            dashboard_connections.clear()
            dashboard_connections.update(saved)

    @pytest.mark.asyncio
    async def test_removes_dead_connections(self):
        """Verify dead dashboard connections are discarded."""
        dead_ws = AsyncMock()
        dead_ws.send_text = AsyncMock(side_effect=Exception("closed"))

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = []
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[agents_result, jobs_result])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        dashboard_connections.add(dead_ws)
        try:
            with patch(
                "concerto_controller.notifications.async_session",
                return_value=mock_cm,
            ):
                await notify_dashboards()
            assert dead_ws not in dashboard_connections
        finally:
            dashboard_connections.clear()
            dashboard_connections.update(saved)

    @pytest.mark.asyncio
    async def test_snapshot_with_null_fields(self):
        """Verify snapshot handles agents/jobs with null optional fields."""
        agent = AgentRecord(
            id=uuid.uuid4(),
            name="a1",
            capabilities=[],
            status=AgentStatus.OFFLINE,
            last_heartbeat=None,
            current_job_id=None,
        )
        job = JobRecord(
            id=uuid.uuid4(),
            product="vehicle_gateway",
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
            result=None,
            duration=None,
        )

        agents_result = MagicMock()
        agents_result.scalars.return_value.all.return_value = [agent]
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [job]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[agents_result, jobs_result])

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_ws = AsyncMock()

        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        dashboard_connections.add(mock_ws)
        try:
            with patch(
                "concerto_controller.notifications.async_session",
                return_value=mock_cm,
            ):
                await notify_dashboards()
            mock_ws.send_text.assert_awaited_once()
        finally:
            dashboard_connections.clear()
            dashboard_connections.update(saved)


class TestDashboardWebsocket:
    """Tests for the dashboard_websocket handler."""

    @pytest.mark.asyncio
    async def test_connects_and_receives_commands(self):
        """Verify dashboard WS accepts, sends snapshot, and dispatches commands."""
        remove_msg = DashboardRemoveAgentMessage(agent_id=uuid.uuid4())
        msg_idx = 0

        async def recv_text():
            nonlocal msg_idx
            msg_idx += 1
            if msg_idx == 1:
                return remove_msg.model_dump_json()
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        try:
            with (
                patch(
                    "concerto_controller.api.ws.dashboard.notify_dashboards",
                    new_callable=AsyncMock,
                ),
                patch(
                    "concerto_controller.api.ws.dashboard._handle_remove_agent",
                    new_callable=AsyncMock,
                ) as mock_remove,
            ):
                await dashboard_websocket(ws)

            ws.accept.assert_awaited_once()
            mock_remove.assert_awaited_once_with(remove_msg.agent_id)
            assert ws not in dashboard_connections
        finally:
            dashboard_connections.clear()
            dashboard_connections.update(saved)

    @pytest.mark.asyncio
    async def test_dispatches_create_job(self):
        """Verify dashboard WS dispatches create_job commands."""
        create_msg = DashboardCreateJobMessage(
            product=Product.VEHICLE_GATEWAY, duration=5.0
        )
        msg_idx = 0

        async def recv_text():
            nonlocal msg_idx
            msg_idx += 1
            if msg_idx == 1:
                return create_msg.model_dump_json()
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        try:
            with (
                patch(
                    "concerto_controller.api.ws.dashboard.notify_dashboards",
                    new_callable=AsyncMock,
                ),
                patch(
                    "concerto_controller.api.ws.dashboard._handle_create_job",
                    new_callable=AsyncMock,
                ) as mock_create,
            ):
                await dashboard_websocket(ws)

            mock_create.assert_awaited_once_with(Product.VEHICLE_GATEWAY, 5.0)
        finally:
            dashboard_connections.clear()
            dashboard_connections.update(saved)

    @pytest.mark.asyncio
    async def test_handles_generic_exception(self):
        """Verify generic exception in WS loop is caught."""

        async def recv_text():
            raise RuntimeError("unexpected")

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        try:
            with patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ):
                await dashboard_websocket(ws)
            assert ws not in dashboard_connections
        finally:
            dashboard_connections.clear()
            dashboard_connections.update(saved)

    @pytest.mark.asyncio
    async def test_unknown_message_falls_through(self):
        """Cover branch 101→95: message that's neither RemoveAgent nor CreateJob."""
        msg_idx = 0

        async def recv_text():
            nonlocal msg_idx
            msg_idx += 1
            if msg_idx == 1:
                return '{"type": "unknown"}'
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        saved = dashboard_connections.copy()
        dashboard_connections.clear()
        try:
            with (
                patch(
                    "concerto_controller.api.ws.dashboard.notify_dashboards",
                    new_callable=AsyncMock,
                ),
                patch(
                    "concerto_controller.api.ws.dashboard.parse_dashboard_message",
                    return_value=MagicMock(),
                ),
            ):
                await dashboard_websocket(ws)
        finally:
            dashboard_connections.clear()
            dashboard_connections.update(saved)


class TestHandleRemoveAgent:
    """Tests for _handle_remove_agent."""

    @pytest.mark.asyncio
    async def test_removes_existing_agent(self):
        """Verify _handle_remove_agent deletes the agent and re-queues jobs."""
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="rm-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
        )
        running_job = JobRecord(
            id=uuid.uuid4(),
            product="vehicle_gateway",
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )

        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = agent
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [running_job]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[agent_result, jobs_result])
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_ws = AsyncMock()
        test_connections = {agent_id: mock_ws}

        with (
            patch(
                "concerto_controller.api.ws.dashboard.async_session",
                return_value=mock_cm,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.agent_connections",
                test_connections,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.notifications.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_remove_agent(agent_id)

        assert running_job.status == JobStatus.QUEUED
        mock_ws.send_text.assert_awaited_once()
        mock_ws.close.assert_awaited_once()
        mock_session.delete.assert_awaited_once_with(agent)

    @pytest.mark.asyncio
    async def test_noop_when_agent_not_found(self):
        """Verify _handle_remove_agent is a no-op if agent doesn't exist."""
        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=agent_result)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "concerto_controller.api.ws.dashboard.async_session", return_value=mock_cm
        ):
            await _handle_remove_agent(uuid.uuid4())

        mock_session.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_ws_close_exception_suppressed(self):
        """Verify exception during WS close in remove is suppressed."""
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="rm-err",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
        )

        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = agent
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[agent_result, jobs_result])
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        mock_ws = AsyncMock()
        mock_ws.send_text = AsyncMock(side_effect=Exception("gone"))
        test_connections = {agent_id: mock_ws}

        with (
            patch(
                "concerto_controller.api.ws.dashboard.async_session",
                return_value=mock_cm,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.agent_connections",
                test_connections,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.notifications.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_remove_agent(agent_id)  # should not raise

        mock_session.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_removes_agent_with_completed_job(self):
        """Verify completed jobs just have agent_id cleared, not re-queued."""
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="rm-done",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
        )
        completed_job = JobRecord(
            id=uuid.uuid4(),
            product="vehicle_gateway",
            status=JobStatus.COMPLETED,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )

        agent_result = MagicMock()
        agent_result.scalar_one_or_none.return_value = agent
        jobs_result = MagicMock()
        jobs_result.scalars.return_value.all.return_value = [completed_job]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=[agent_result, jobs_result])
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.dashboard.async_session",
                return_value=mock_cm,
            ),
            patch("concerto_controller.api.ws.dashboard.agent_connections", {}),
            patch(
                "concerto_controller.api.ws.dashboard.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.notifications.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_remove_agent(agent_id)

        assert completed_job.status == JobStatus.COMPLETED
        assert completed_job.assigned_agent_id is None


class TestHandleCreateJob:
    """Tests for _handle_create_job."""

    @pytest.mark.asyncio
    async def test_creates_job_and_dispatches(self):
        """Verify _handle_create_job creates a job and triggers dispatch."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.dashboard.async_session",
                return_value=mock_cm,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.try_dispatch",
                new_callable=AsyncMock,
            ) as mock_dispatch,
        ):
            await _handle_create_job(Product.VEHICLE_GATEWAY, 5.0)

        mock_session.add.assert_called_once()
        added_job = mock_session.add.call_args[0][0]
        assert added_job.product == Product.VEHICLE_GATEWAY
        assert added_job.status == JobStatus.QUEUED
        assert added_job.duration == 5.0
        mock_dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_job_without_duration(self):
        """Verify _handle_create_job works with None duration."""
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.dashboard.async_session",
                return_value=mock_cm,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.try_dispatch",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_create_job(Product.ASSET_GATEWAY, None)

        added_job = mock_session.add.call_args[0][0]
        assert added_job.duration is None
        assert added_job.duration is None
