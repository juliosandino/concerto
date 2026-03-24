"""Tests for the agent WebSocket client."""

# pylint: disable=protected-access,redefined-outer-name

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions
from concerto_agent.client import AgentClient
from concerto_shared.enums import Product
from concerto_shared.messages import (
    DisconnectMessage,
    HeartbeatMessage,
    JobAssignMessage,
    RegisterAckMessage,
    RegisterMessage,
)


@pytest.fixture
def client():
    """Create a default AgentClient for testing."""
    return AgentClient(
        agent_name="test-agent",
        capabilities=[Product.VEHICLE_GATEWAY],
        controller_url="ws://localhost:8000/ws/agent",
        heartbeat_interval=0.01,
        reconnect_base_delay=0.01,
        reconnect_max_delay=0.05,
    )


class TestAgentClientInit:
    """Tests for AgentClient construction."""

    def test_constructor_stores_fields(self, client):
        """Verify all constructor args are stored correctly."""
        assert client.agent_name == "test-agent"
        assert client.capabilities == [Product.VEHICLE_GATEWAY]
        assert client.controller_url == "ws://localhost:8000/ws/agent"
        assert client.heartbeat_interval == 0.01
        assert client.reconnect_base_delay == 0.01
        assert client.reconnect_max_delay == 0.05
        assert client.on_message is None
        assert client.agent_id is None
        assert client._ws is None
        assert client._running is False

    def test_constructor_with_on_message(self):
        """Verify on_message callback is stored."""
        callback = AsyncMock()
        c = AgentClient(
            agent_name="a",
            capabilities=[],
            controller_url="ws://x",
            on_message=callback,
        )
        assert c.on_message is callback


class TestAgentClientStop:
    """Tests for the stop method."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false_and_closes_ws(self, client):
        """Verify stop clears _running and closes the websocket."""
        client._running = True
        mock_ws = AsyncMock()
        client._ws = mock_ws
        await client.stop()
        assert client._running is False
        mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_when_no_ws(self, client):
        """Verify stop works cleanly when no websocket exists."""
        client._running = True
        await client.stop()
        assert client._running is False


class TestAgentClientSend:
    """Tests for the send method."""

    @pytest.mark.asyncio
    async def test_send_writes_json(self, client):
        """Verify send serializes and sends via websocket."""
        mock_ws = AsyncMock()
        client._ws = mock_ws
        msg = HeartbeatMessage(agent_id=uuid.uuid4())
        await client.send(msg)
        mock_ws.send.assert_awaited_once_with(msg.model_dump_json())

    @pytest.mark.asyncio
    async def test_send_noop_when_no_ws(self, client):
        """Verify send is a no-op when _ws is None."""
        msg = HeartbeatMessage(agent_id=uuid.uuid4())
        await client.send(msg)  # should not raise


class TestAgentClientSession:
    """Tests for the _session method (register, heartbeat, receive)."""

    @pytest.mark.asyncio
    async def test_session_registers_and_sets_agent_id(self, client):
        """Verify _session sends register message and stores the ack agent_id."""
        agent_id = uuid.uuid4()
        ack = RegisterAckMessage(agent_id=agent_id)
        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=ack.model_dump_json())

        # Make the TaskGroup tasks end immediately
        async def fake_heartbeat(_ws_arg):  # pylint: disable=unused-argument
            pass

        async def fake_receive(_ws_arg):  # pylint: disable=unused-argument
            pass

        with (
            patch.object(client, "_heartbeat_loop", side_effect=fake_heartbeat),
            patch.object(client, "_receive_loop", side_effect=fake_receive),
        ):
            await client._session(ws)

        assert client.agent_id == agent_id
        # First call: register message
        sent_raw = ws.send.call_args_list[0][0][0]
        reg = RegisterMessage.model_validate_json(sent_raw)
        assert reg.agent_name == "test-agent"
        assert reg.capabilities == [Product.VEHICLE_GATEWAY]

    @pytest.mark.asyncio
    async def test_session_returns_on_unexpected_ack(self, client):
        """Verify _session returns early if server sends non-RegisterAck."""
        hb = HeartbeatMessage(agent_id=uuid.uuid4())
        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=hb.model_dump_json())

        await client._session(ws)
        # agent_id should NOT be set
        assert client.agent_id is None

    @pytest.mark.asyncio
    async def test_session_reraises_connection_closed(self, client):
        """Verify ConnectionClosed from TaskGroup is re-raised."""
        agent_id = uuid.uuid4()
        ack = RegisterAckMessage(agent_id=agent_id)
        ws = AsyncMock()
        ws.recv = AsyncMock(return_value=ack.model_dump_json())

        exc = websockets.exceptions.ConnectionClosedError(rcvd=None, sent=None)

        async def failing_heartbeat(_ws_arg):  # pylint: disable=unused-argument
            raise exc

        async def fake_receive(_ws_arg):  # pylint: disable=unused-argument
            await asyncio.sleep(10)

        with (
            patch.object(client, "_heartbeat_loop", side_effect=failing_heartbeat),
            patch.object(client, "_receive_loop", side_effect=fake_receive),
            pytest.raises(websockets.exceptions.ConnectionClosedError),
        ):
            await client._session(ws)


class TestHeartbeatLoop:
    """Tests for the _heartbeat_loop method."""

    @pytest.mark.asyncio
    async def test_sends_heartbeats(self, client):
        """Verify heartbeats are sent periodically."""
        client._running = True
        client.agent_id = uuid.uuid4()
        ws = AsyncMock()
        send_count = 0

        async def counting_send(_data):  # pylint: disable=unused-argument
            nonlocal send_count
            send_count += 1
            if send_count >= 2:
                client._running = False

        ws.send = AsyncMock(side_effect=counting_send)
        await client._heartbeat_loop(ws)
        assert send_count >= 2

        # Verify sent messages are HeartbeatMessages
        raw = ws.send.call_args_list[0][0][0]
        parsed = HeartbeatMessage.model_validate_json(raw)
        assert parsed.agent_id == client.agent_id


class TestReceiveLoop:
    """Tests for the _receive_loop method."""

    @pytest.mark.asyncio
    async def test_disconnect_message_stops_client(self, client):
        """Verify receiving a DisconnectMessage sets _running=False and closes."""
        client._running = True
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
        await client._receive_loop(ws)
        assert client._running is False
        ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatches_to_on_message(self, client):
        """Verify non-disconnect messages are dispatched to on_message."""
        client._running = True
        callback = AsyncMock()
        client.on_message = callback
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
        await client._receive_loop(ws)
        callback.assert_awaited_once()
        dispatched = callback.call_args[0][0]
        assert isinstance(dispatched, JobAssignMessage)
        assert dispatched.job_id == job_id

    @pytest.mark.asyncio
    async def test_no_callback_skips_dispatch(self, client):
        """Verify messages are silently consumed when on_message is None."""
        client._running = True
        client.on_message = None
        assign = JobAssignMessage(job_id=uuid.uuid4(), product=Product.VEHICLE_GATEWAY)
        ws = AsyncMock()
        ws.__aiter__ = lambda _self: _self  # noqa: E731
        msgs = iter([assign.model_dump_json()])

        async def anext_fn(_self):  # pylint: disable=unused-argument
            try:
                return next(msgs)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        ws.__anext__ = anext_fn
        await client._receive_loop(ws)  # should not raise


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
    async def test_run_reconnects_on_connection_error(self, client):
        """Verify run retries on ConnectionError with exponential backoff."""
        call_count = 0

        def fake_connect(_url):  # pylint: disable=unused-argument
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                client._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.client.websockets.connect", side_effect=fake_connect),
            patch("concerto_agent.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            await client.run()
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run_stops_on_4002_rejection(self, client):
        """Verify run stops immediately on 4002 close code (registration rejected)."""
        rcvd = MagicMock()
        rcvd.code = 4002
        rcvd.reason = "Duplicate agent name"
        exc = websockets.exceptions.ConnectionClosedError(rcvd=rcvd, sent=None)

        with patch(
            "concerto_agent.client.websockets.connect",
            side_effect=self._connect_cm_raising(exc),
        ):
            await client.run()
        assert client._ws is None

    @pytest.mark.asyncio
    async def test_run_retries_on_1012_service_restart(self, client):
        """Verify run uses a fixed 10s delay on 1012 (service restart)."""
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
                client._running = False
                cm.__aenter__ = AsyncMock(side_effect=ConnectionError("stop"))
            else:
                cm.__aenter__ = AsyncMock(side_effect=exc_1012)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.client.websockets.connect", side_effect=fake_connect),
            patch(
                "concerto_agent.client.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep,
        ):
            await client.run()

        # First sleep should be 10 seconds (1012 handler)
        mock_sleep.assert_any_call(10)

    @pytest.mark.asyncio
    async def test_run_stops_on_cancelled(self, client):
        """Verify run breaks on CancelledError."""

        with patch(
            "concerto_agent.client.websockets.connect",
            side_effect=self._connect_cm_raising(asyncio.CancelledError()),
        ):
            await client.run()
        assert client._ws is None

    @pytest.mark.asyncio
    async def test_run_successful_session(self, client):
        """Verify run flows through a successful session and resets delay."""
        call_count = 0

        async def fake_session(_ws):  # pylint: disable=unused-argument
            nonlocal call_count
            call_count += 1
            client._running = False

        mock_ws = AsyncMock()

        def fake_connect(_url):  # pylint: disable=unused-argument
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=mock_ws)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.client.websockets.connect", side_effect=fake_connect),
            patch.object(client, "_session", side_effect=fake_session),
        ):
            await client.run()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_run_exponential_backoff_capped(self, client):
        """Verify exponential backoff is capped at reconnect_max_delay."""
        sleep_durations = []
        call_count = 0

        def fake_connect(_url):  # pylint: disable=unused-argument
            nonlocal call_count
            call_count += 1
            if call_count >= 6:
                client._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=OSError("network unreachable"))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        async def tracking_sleep(duration):
            sleep_durations.append(duration)

        with (
            patch("concerto_agent.client.websockets.connect", side_effect=fake_connect),
            patch("concerto_agent.client.asyncio.sleep", side_effect=tracking_sleep),
        ):
            await client.run()

        # Delays should never exceed reconnect_max_delay (0.05)
        for d in sleep_durations:
            assert d <= client.reconnect_max_delay

    @pytest.mark.asyncio
    async def test_run_clears_ws_on_exit(self, client):
        """Verify _ws is set to None after run() exits."""

        def fake_connect(_url):  # pylint: disable=unused-argument
            client._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=ConnectionError("done"))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.client.websockets.connect", side_effect=fake_connect),
            patch("concerto_agent.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            await client.run()
        assert client._ws is None

    @pytest.mark.asyncio
    async def test_run_websocket_exception(self, client):
        """Verify WebSocketException triggers reconnection."""
        call_count = 0

        def fake_connect(_url):  # pylint: disable=unused-argument
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                client._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(
                side_effect=websockets.exceptions.WebSocketException("error")
            )
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with (
            patch("concerto_agent.client.websockets.connect", side_effect=fake_connect),
            patch("concerto_agent.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            await client.run()
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run_connection_lost_while_stopped(self, client):
        """Verify run exits cleanly if stopped during a connection error."""

        def fake_connect(_url):  # pylint: disable=unused-argument
            client._running = False
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(side_effect=ConnectionError("refused"))
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with patch(
            "concerto_agent.client.websockets.connect", side_effect=fake_connect
        ):
            await client.run()
        assert client._ws is None
