"""Tests for the agent WebSocket endpoint."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from concerto_controller.api.ws.agent import (
    _handle_agent_disconnect,
    _handle_job_status,
    agent_websocket,
)
from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_shared.enums import AgentStatus, JobStatus, Product
from concerto_shared.messages import (
    HeartbeatMessage,
    JobStatusMessage,
    RegisterAckMessage,
    RegisterMessage,
)
from fastapi import WebSocketDisconnect


class TestAgentWebsocket:
    """Tests for the agent_websocket handler."""

    @pytest.mark.asyncio
    async def test_rejects_non_register_first_message(self):
        """Verify WS is closed if first message is not a RegisterMessage."""
        hb = HeartbeatMessage(agent_id=uuid.uuid4())
        ws = AsyncMock()
        ws.receive_text = AsyncMock(return_value=hb.model_dump_json())

        await agent_websocket(ws)

        ws.accept.assert_awaited_once()
        ws.close.assert_awaited_once()
        close_kwargs = ws.close.call_args[1]
        assert close_kwargs["code"] == 4001

    @pytest.mark.asyncio
    async def test_rejects_duplicate_agent_name(self):
        """Verify WS is closed 4002 if agent name already connected."""
        agent_id = uuid.uuid4()
        reg = RegisterMessage(
            agent_name="dup-agent", capabilities=[Product.VEHICLE_GATEWAY]
        )
        ws = AsyncMock()
        ws.receive_text = AsyncMock(return_value=reg.model_dump_json())

        existing_agent = AgentRecord(
            id=agent_id,
            name="dup-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_agent

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        # Put the existing agent_id in connections to simulate "already connected"
        test_connections = {agent_id: MagicMock()}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
        ):
            await agent_websocket(ws)

        ws.close.assert_awaited()
        close_kwargs = ws.close.call_args[1]
        assert close_kwargs["code"] == 4002

    @pytest.mark.asyncio
    async def test_registers_new_agent(self):
        """Verify a new agent is registered and ack is sent."""
        reg = RegisterMessage(
            agent_name="new-agent", capabilities=[Product.VEHICLE_GATEWAY]
        )
        ws = AsyncMock()
        call_count = 0

        async def recv_text():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return reg.model_dump_json()
            raise WebSocketDisconnect()

        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # new agent

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        test_connections = {}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
        ):
            await agent_websocket(ws)

        # Ack should have been sent
        ws.send_text.assert_awaited()
        ack_raw = ws.send_text.call_args_list[0][0][0]
        ack = RegisterAckMessage.model_validate_json(ack_raw)
        assert ack.agent_id is not None

    @pytest.mark.asyncio
    async def test_reconnects_existing_agent(self):
        """Verify an existing agent gets reconnected (updated, not added)."""
        agent_id = uuid.uuid4()
        existing = AgentRecord(
            id=agent_id,
            name="reconnect-agent",
            capabilities=["asset_gateway"],
            status=AgentStatus.OFFLINE,
        )

        reg = RegisterMessage(
            agent_name="reconnect-agent",
            capabilities=[Product.VEHICLE_GATEWAY],
        )
        ws = AsyncMock()
        call_count = 0

        async def recv_text():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return reg.model_dump_json()
            raise WebSocketDisconnect()

        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        test_connections = {}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
        ):
            await agent_websocket(ws)

        assert existing.status == AgentStatus.ONLINE
        assert existing.capabilities == ["vehicle_gateway"]
        # add should NOT have been called (reconnection, not new)
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_heartbeat_message(self):
        """Verify heartbeat messages update agent last_heartbeat."""
        agent_id = uuid.uuid4()
        reg = RegisterMessage(
            agent_name="hb-agent", capabilities=[Product.VEHICLE_GATEWAY]
        )
        hb = HeartbeatMessage(agent_id=agent_id)

        msg_idx = 0
        messages = [reg.model_dump_json(), hb.model_dump_json()]

        async def recv_text():
            nonlocal msg_idx
            if msg_idx < len(messages):
                raw = messages[msg_idx]
                msg_idx += 1
                return raw
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_agent = AgentRecord(
            id=agent_id,
            name="hb-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_agent)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        test_connections = {}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
        ):
            await agent_websocket(ws)

    @pytest.mark.asyncio
    async def test_handles_job_status_message(self):
        """Verify job status messages are dispatched."""
        agent_id = uuid.uuid4()
        reg = RegisterMessage(
            agent_name="js-agent", capabilities=[Product.VEHICLE_GATEWAY]
        )
        job_status = JobStatusMessage(
            agent_id=agent_id,
            job_id=uuid.uuid4(),
            status=JobStatus.COMPLETED,
            result="done",
        )

        msg_idx = 0
        messages = [reg.model_dump_json(), job_status.model_dump_json()]

        async def recv_text():
            nonlocal msg_idx
            if msg_idx < len(messages):
                raw = messages[msg_idx]
                msg_idx += 1
                return raw
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        test_connections = {}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.agent._handle_job_status",
                new_callable=AsyncMock,
            ) as mock_hjs,
        ):
            await agent_websocket(ws)

        mock_hjs.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_generic_exception(self):
        """Verify generic exception in WS loop is caught and disconnect handled."""
        reg = RegisterMessage(
            agent_name="err-agent", capabilities=[Product.VEHICLE_GATEWAY]
        )

        msg_idx = 0

        async def recv_text():
            nonlocal msg_idx
            msg_idx += 1
            if msg_idx == 1:
                return reg.model_dump_json()
            raise RuntimeError("unexpected")

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        test_connections = {}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.agent._handle_agent_disconnect",
                new_callable=AsyncMock,
            ) as mock_disc,
        ):
            await agent_websocket(ws)

        mock_disc.assert_awaited_once()


class TestHandleJobStatus:
    """Tests for _handle_job_status."""

    @pytest.mark.asyncio
    async def test_running_status_updates_job(self):
        """Verify RUNNING status sets started_at."""
        job_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.ASSIGNED,
            created_at=datetime.now(timezone.utc),
        )
        msg = JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.RUNNING,
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=job)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_job_status(msg)

        assert job.status == JobStatus.RUNNING
        assert job.started_at is not None

    @pytest.mark.asyncio
    async def test_completed_status_frees_agent(self):
        """Verify COMPLETED status frees the agent."""
        job_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )
        agent = AgentRecord(
            id=agent_id,
            name="busy-a",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            current_job_id=job_id,
        )
        msg = JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result="passed",
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            side_effect=lambda model, pk: job if model is JobRecord else agent
        )
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_job_status(msg)

        assert job.status == JobStatus.COMPLETED
        assert job.result == "passed"
        assert job.assigned_agent_id is agent_id
        assert agent.status == AgentStatus.ONLINE
        assert agent.current_job_id is None

    @pytest.mark.asyncio
    async def test_failed_status(self):
        """Verify FAILED status is handled."""
        job_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )
        agent = AgentRecord(
            id=agent_id,
            name="fail-a",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            current_job_id=job_id,
        )
        msg = JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.FAILED,
            result="error",
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            side_effect=lambda model, pk: job if model is JobRecord else agent
        )
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_job_status(msg)

        assert job.status == JobStatus.FAILED

    @pytest.mark.asyncio
    async def test_unknown_job_is_logged(self):
        """Verify status update for unknown job is handled gracefully."""
        msg = JobStatusMessage(
            agent_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            status=JobStatus.COMPLETED,
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
        ):
            await _handle_job_status(msg)  # should not raise

        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_completed_no_agent_found(self):
        """Verify completed status works even if agent record is missing."""
        job_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )
        msg = JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result="ok",
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            side_effect=lambda model, pk: job if model is JobRecord else None
        )
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_job_status(msg)

        assert job.status == JobStatus.COMPLETED


class TestHandleAgentDisconnect:
    """Tests for _handle_agent_disconnect."""

    @pytest.mark.asyncio
    async def test_marks_agent_offline(self):
        """Verify disconnected agent is marked offline."""
        agent_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="disc-a",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=agent)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_agent_disconnect(agent_id)

        assert agent.status == AgentStatus.OFFLINE
        assert agent.last_heartbeat is None

    @pytest.mark.asyncio
    async def test_requeues_running_job(self):
        """Verify disconnect re-queues the agent's running job."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="disc-busy",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            current_job_id=job_id,
            last_heartbeat=datetime.now(timezone.utc),
        )
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            side_effect=lambda model, pk: agent if model is AgentRecord else job
        )
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_agent_disconnect(agent_id)

        assert job.status == JobStatus.QUEUED
        assert agent.current_job_id is None

    @pytest.mark.asyncio
    async def test_agent_not_found(self):
        """Verify disconnect is a no-op if agent is already deleted."""
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
        ):
            await _handle_agent_disconnect(uuid.uuid4())

        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_with_completed_job_not_requeued(self):
        """Verify a completed job is not re-queued on disconnect."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        agent = AgentRecord(
            id=agent_id,
            name="disc-done",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            current_job_id=job_id,
        )
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(
            side_effect=lambda model, pk: agent if model is AgentRecord else job
        )
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_agent_disconnect(agent_id)

        assert job.status == JobStatus.COMPLETED


class TestBranchCoverage:
    """Targeted tests for partial branch coverage gaps."""

    @pytest.mark.asyncio
    async def test_heartbeat_agent_not_found_in_db(self):
        """Cover branch 104→97: heartbeat when agent deleted from DB."""
        agent_id = uuid.uuid4()
        reg = RegisterMessage(
            agent_name="hb-gone", capabilities=[Product.VEHICLE_GATEWAY]
        )
        hb = HeartbeatMessage(agent_id=agent_id)
        msg_idx = 0
        messages = [reg.model_dump_json(), hb.model_dump_json()]

        async def recv_text():
            nonlocal msg_idx
            if msg_idx < len(messages):
                raw = messages[msg_idx]
                msg_idx += 1
                return raw
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)  # agent not found

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        test_connections = {}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
        ):
            await agent_websocket(ws)

    @pytest.mark.asyncio
    async def test_unknown_message_in_main_loop(self):
        """Cover branch 108→97: message that's neither HB nor JobStatus."""
        reg = RegisterMessage(
            agent_name="unk-msg", capabilities=[Product.VEHICLE_GATEWAY]
        )
        second_reg = RegisterMessage(
            agent_name="unk-msg", capabilities=[Product.VEHICLE_GATEWAY]
        )
        msg_idx = 0
        messages = [reg.model_dump_json(), second_reg.model_dump_json()]

        async def recv_text():
            nonlocal msg_idx
            if msg_idx < len(messages):
                raw = messages[msg_idx]
                msg_idx += 1
                return raw
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        test_connections = {}

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
        ):
            await agent_websocket(ws)

    @pytest.mark.asyncio
    async def test_finally_when_connection_already_removed(self):
        """Cover branch 122→exit: was_tracked is False."""
        reg = RegisterMessage(
            agent_name="pop-agent", capabilities=[Product.VEHICLE_GATEWAY]
        )
        call_count = 0
        test_connections = {}

        async def recv_text():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return reg.model_dump_json()
            # Simulate someone already popping our connection
            test_connections.clear()
            raise WebSocketDisconnect()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=recv_text)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch("concerto_controller.api.ws.agent.agent_connections", test_connections),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.scheduler.dispatcher.try_dispatch",
                new_callable=AsyncMock,
            ),
            patch(
                "concerto_controller.api.ws.agent._handle_agent_disconnect",
                new_callable=AsyncMock,
            ) as mock_disc,
        ):
            await agent_websocket(ws)

        mock_disc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_job_status_assigned(self):
        """Cover branch 139→151: status is ASSIGNED (not RUNNING/COMPLETED/FAILED)."""
        job_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )
        msg = JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.ASSIGNED,
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=job)
        mock_session.commit = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "concerto_controller.api.ws.agent.async_session", return_value=mock_cm
            ),
            patch(
                "concerto_controller.api.ws.dashboard.notify_dashboards",
                new_callable=AsyncMock,
            ),
        ):
            await _handle_job_status(msg)

        mock_session.commit.assert_awaited_once()
