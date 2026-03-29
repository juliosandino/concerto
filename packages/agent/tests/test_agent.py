"""Tests for the agent WebSocket client."""

# pylint: disable=protected-access,redefined-outer-name

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions
from concerto_agent.agent import ConcertoAgent
from concerto_shared.enums import Product
from concerto_shared.messages import (
    DisconnectMessage,
    HeartbeatMessage,
    JobAssignMessage,
    RegisterAckMessage,
    RegisterMessage,
)


@pytest.fixture
def agent():
    """Create a default ConcertoAgent for testing."""
    return ConcertoAgent(
        agent_name="test-agent",
        capabilities=[Product.VEHICLE_GATEWAY],
        controller_url="ws://localhost:8000/ws/agent",
        heartbeat_interval=0.01,
        reconnect_base_delay=0.01,
        reconnect_max_delay=0.05,
    )


class TestConcertoAgentInit:
    """Tests for ConcertoAgent construction."""

    def test_constructor_stores_fields(self, agent):
        """Verify all constructor args are stored correctly."""
        assert agent.agent_name == "test-agent"
        assert agent.capabilities == [Product.VEHICLE_GATEWAY]
        assert agent.controller_url == "ws://localhost:8000/ws/agent"
        assert agent.heartbeat_interval == 0.01
        assert agent.reconnect_base_delay == 0.01
        assert agent.reconnect_max_delay == 0.05
        assert agent.agent_id is None
        assert agent._ws is None
        assert agent._running is False


class TestConcertoAgentStop:
    """Tests for the stop method."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false_and_closes_ws(self, agent):
        """Verify stop clears _running and closes the websocket."""
        agent._running = True
        mock_ws = AsyncMock()
        agent._ws = mock_ws
        msg = DisconnectMessage(reason="shutdown")
        await agent.stop(msg)
        assert agent._running is False
        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_when_no_ws(self, agent):
        """Verify stop works cleanly when no websocket exists."""
        agent._running = True
        msg = DisconnectMessage(reason="shutdown")
        await agent.stop(msg)
        assert agent._running is False


class TestConcertoAgentSend:
    """Tests for the send method."""

    @pytest.mark.asyncio
    async def test_send_writes_json(self, agent):
        """Verify send serializes and sends via websocket."""
        mock_ws = AsyncMock()
        agent._ws = mock_ws
        msg = HeartbeatMessage(agent_id=uuid.uuid4())
        await agent.send(msg)
        mock_ws.send.assert_awaited_once_with(msg.model_dump_json())

    @pytest.mark.asyncio
    async def test_send_noop_when_no_ws(self, agent):
        """Verify send is a no-op when _ws is None."""
        msg = HeartbeatMessage(agent_id=uuid.uuid4())
        await agent.send(msg)  # should not raise


class TestConcertoAgentSession:
    """Tests for the _session method (register, heartbeat, receive)."""

    @pytest.mark.asyncio
    async def test_session_registers_and_sets_agent_id(self, agent):
        """Verify _session sends register message and stores the ack agent_id."""
        agent_id = uuid.uuid4()
        ack = RegisterAckMessage(agent_id=agent_id)
        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=ack.model_dump_json())
        agent._ws = ws

        async def fake_heartbeat():
            pass

        async def fake_receive():
            pass

        with (
            patch.object(agent, "_heartbeat_loop", side_effect=fake_heartbeat),
            patch.object(agent, "_receive_loop", side_effect=fake_receive),
        ):
            await agent._session()

        assert agent.agent_id == agent_id
        # First call: register message
        sent_raw = ws.send.call_args_list[0][0][0]
        reg = RegisterMessage.model_validate_json(sent_raw)
        assert reg.agent_name == "test-agent"
        assert reg.capabilities == [Product.VEHICLE_GATEWAY]

    @pytest.mark.asyncio
    async def test_session_returns_on_unexpected_ack(self, agent):
        """Verify _session returns early if server sends non-RegisterAck."""
        hb = HeartbeatMessage(agent_id=uuid.uuid4())
        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=hb.model_dump_json())
        agent._ws = ws

        await agent._session()
        # agent_id should NOT be set
        assert agent.agent_id is None

    @pytest.mark.asyncio
    async def test_session_reraises_connection_closed(self, agent):
        """Verify ConnectionClosed from TaskGroup is re-raised."""
        agent_id = uuid.uuid4()
        ack = RegisterAckMessage(agent_id=agent_id)
        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=ack.model_dump_json())
        agent._ws = ws

        exc = websockets.exceptions.ConnectionClosedError(rcvd=None, sent=None)

        async def failing_heartbeat():
            raise exc

        async def fake_receive():
            await asyncio.sleep(10)

        with (
            patch.object(agent, "_heartbeat_loop", side_effect=failing_heartbeat),
            patch.object(agent, "_receive_loop", side_effect=fake_receive),
            pytest.raises(websockets.exceptions.ConnectionClosedError),
        ):
            await agent._session()


class TestHeartbeatLoop:
    """Tests for the _heartbeat_loop method."""

    @pytest.mark.asyncio
    async def test_sends_heartbeats(self, agent):
        """Verify heartbeats are sent periodically."""
        agent._running = True
        agent.agent_id = uuid.uuid4()
        ws = AsyncMock()
        agent._ws = ws
        send_count = 0

        async def counting_send(data):  # pylint: disable=unused-argument
            nonlocal send_count
            send_count += 1
            if send_count >= 2:
                agent._running = False

        ws.send = AsyncMock(side_effect=counting_send)
        await agent._heartbeat_loop()
        assert send_count >= 2

        # Verify sent messages are HeartbeatMessages
        raw = ws.send.call_args_list[0][0][0]
        parsed = HeartbeatMessage.model_validate_json(raw)
        assert parsed.agent_id == agent.agent_id


class TestReceiveLoop:
    """Tests for the _receive_loop method."""

    @pytest.mark.asyncio
    async def test_disconnect_message_stops_client(self, agent):
        """Verify receiving a DisconnectMessage calls stop."""
        agent._running = True
        disc = DisconnectMessage(reason="shutdown")
        ws = AsyncMock()
        ws.__aiter__ = lambda _self: _self  # noqa: E731
        msgs = iter([disc.model_dump_json()])

        async def anext_fn(_self):  # pylint: disable=unused-argument
            try:
                return next(msgs)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        ws.__anext__ = anext_fn
        agent._ws = ws

        with patch.object(agent, "stop", new_callable=AsyncMock) as mock_stop:
            await agent._receive_loop()
            mock_stop.assert_awaited_once()
            stop_arg = mock_stop.call_args[0][0]
            assert isinstance(stop_arg, DisconnectMessage)

    @pytest.mark.asyncio
    async def test_job_assign_dispatches_execute_job(self, agent):
        """Verify JobAssignMessage spawns execute_job task."""
        agent._running = True
        agent.agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        assign = JobAssignMessage(job_id=job_id, product=Product.VEHICLE_GATEWAY)
        ws = AsyncMock()
        ws.__aiter__ = lambda _self: _self  # noqa: E731
        msgs = iter([assign.model_dump_json()])

        async def anext_fn(_self):  # pylint: disable=unused-argument
            try:
                return next(msgs)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        ws.__anext__ = anext_fn
        agent._ws = ws

        with patch("concerto_agent.agent.asyncio.create_task") as mock_task:
            await agent._receive_loop()
            mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_unrecognized_message_logs_warning(self, agent):
        """Verify unrecognized message types are logged and not dispatched."""
        agent._running = True
        hb = HeartbeatMessage(agent_id=uuid.uuid4())
        ws = AsyncMock()
        ws.__aiter__ = lambda _self: _self  # noqa: E731
        msgs = iter([hb.model_dump_json()])

        async def anext_fn(_self):  # pylint: disable=unused-argument
            try:
                return next(msgs)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        ws.__anext__ = anext_fn
        agent._ws = ws

        with patch("concerto_agent.agent.logger.warning") as mock_warn:
            await agent._receive_loop()
            mock_warn.assert_called_once()
            assert "HeartbeatMessage" in mock_warn.call_args[0][0]


class TestRunReconnection:
    """Tests for the run method's reconnection and error handling logic."""

    @staticmethod
    def _connect_cm_raising(exc):
        """Return a factory that builds async CMs whose __aenter__ raises *exc*."""

        def factory(_url):  # pylint: disable=unused-argument
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=exc)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        return factory

    @pytest.mark.asyncio
    async def test_run_reconnects_on_connection_refused(self, agent):
        """Verify run retries on ConnectionRefusedError with exponential backoff."""
        call_count = 0

        def fake_connect(_url):  # pylint: disable=unused-argument
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                agent._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("refused"))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.agent.websockets.connect", side_effect=fake_connect),
            patch("concerto_agent.agent.asyncio.sleep", new_callable=AsyncMock),
        ):
            await agent.run()
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run_stops_on_4002_rejection(self, agent):
        """Verify run stops immediately on 4002 close code (registration rejected)."""
        rcvd = MagicMock()
        rcvd.code = 4002
        rcvd.reason = "Duplicate agent name"
        exc = websockets.exceptions.ConnectionClosedError(rcvd=rcvd, sent=None)

        with patch(
            "concerto_agent.agent.websockets.connect",
            side_effect=self._connect_cm_raising(exc),
        ):
            await agent.run()
        assert agent._ws is None

    @pytest.mark.asyncio
    async def test_run_retries_on_1012_service_restart(self, agent):
        """Verify run retries with backoff on 1012 (service restart)."""
        rcvd = MagicMock()
        rcvd.code = 1012
        rcvd.reason = "Service Restart"
        exc_1012 = websockets.exceptions.ConnectionClosedError(rcvd=rcvd, sent=None)
        call_count = 0

        def fake_connect(_url):  # pylint: disable=unused-argument
            nonlocal call_count
            call_count += 1
            cm = AsyncMock()
            if call_count >= 2:
                agent._running = False
                cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("stop"))
            else:
                cm.__aenter__ = AsyncMock(side_effect=exc_1012)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.agent.websockets.connect", side_effect=fake_connect),
            patch(
                "concerto_agent.agent.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
        ):
            await agent.run()

        # First sleep should use the base delay (backoff)
        mock_sleep.assert_any_call(agent.reconnect_base_delay)

    @pytest.mark.asyncio
    async def test_run_stops_on_cancelled(self, agent):
        """Verify run breaks on CancelledError."""

        with patch(
            "concerto_agent.agent.websockets.connect",
            side_effect=self._connect_cm_raising(asyncio.CancelledError()),
        ):
            await agent.run()
        assert agent._ws is None

    @pytest.mark.asyncio
    async def test_run_successful_session(self, agent):
        """Verify run flows through a successful session and resets delay."""
        call_count = 0

        async def fake_session():
            nonlocal call_count
            call_count += 1
            agent._running = False

        mock_ws = AsyncMock()

        def fake_connect(_url):  # pylint: disable=unused-argument
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=mock_ws)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.agent.websockets.connect", side_effect=fake_connect),
            patch.object(agent, "_session", side_effect=fake_session),
        ):
            await agent.run()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_run_exponential_backoff_capped(self, agent):
        """Verify exponential backoff is capped at reconnect_max_delay."""
        sleep_durations = []
        call_count = 0

        def fake_connect(_url):  # pylint: disable=unused-argument
            nonlocal call_count
            call_count += 1
            if call_count >= 6:
                agent._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("refused"))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        async def tracking_sleep(duration):
            sleep_durations.append(duration)

        with (
            patch("concerto_agent.agent.websockets.connect", side_effect=fake_connect),
            patch("concerto_agent.agent.asyncio.sleep", side_effect=tracking_sleep),
        ):
            await agent.run()

        # Delays should never exceed reconnect_max_delay (0.05)
        for d in sleep_durations:
            assert d <= agent.reconnect_max_delay

    @pytest.mark.asyncio
    async def test_run_clears_ws_on_exit(self, agent):
        """Verify _ws is set to None after run() exits."""

        def fake_connect(_url):  # pylint: disable=unused-argument
            agent._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("done"))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.agent.websockets.connect", side_effect=fake_connect),
            patch("concerto_agent.agent.asyncio.sleep", new_callable=AsyncMock),
        ):
            await agent.run()
        assert agent._ws is None

    @pytest.mark.asyncio
    async def test_run_stops_on_unknown_close_code(self, agent):
        """Verify run stops on an unexpected close code."""
        rcvd = MagicMock()
        rcvd.code = 1001
        rcvd.reason = "Going away"
        exc = websockets.exceptions.ConnectionClosedError(rcvd=rcvd, sent=None)

        with patch(
            "concerto_agent.agent.websockets.connect",
            side_effect=self._connect_cm_raising(exc),
        ):
            await agent.run()
        assert agent._ws is None

    @pytest.mark.asyncio
    async def test_run_stops_on_no_close_frame(self, agent):
        """Verify run stops when close frame is None."""
        exc = websockets.exceptions.ConnectionClosedError(rcvd=None, sent=None)

        with patch(
            "concerto_agent.agent.websockets.connect",
            side_effect=self._connect_cm_raising(exc),
        ):
            await agent.run()
        assert agent._ws is None
