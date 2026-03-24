"""WebSocket client for connecting agents to the controller."""
from __future__ import annotations

import asyncio
import uuid
from typing import Callable

import websockets
from concerto_shared.enums import Product
from concerto_shared.messages import (
    DisconnectMessage,
    HeartbeatMessage,
    RegisterAckMessage,
    RegisterMessage,
    WSMessage,
    parse_message,
)
from loguru import logger
from websockets.asyncio.client import ClientConnection


class AgentClient:
    """WebSocket client that connects to the controller, registers, and
    maintains a heartbeat loop while dispatching incoming messages."""

    def __init__(
        self,
        agent_name: str,
        capabilities: list[Product],
        controller_url: str,
        heartbeat_interval: float = 5.0,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        on_message: Callable[[WSMessage], asyncio.Future] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.capabilities = capabilities
        self.controller_url = controller_url
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.on_message = on_message
        self.agent_id: uuid.UUID | None = None
        self._ws: ClientConnection | None = None
        self._running = False

    async def run(self) -> None:
        """Connect with automatic reconnection using exponential backoff."""
        self._running = True
        delay = self.reconnect_base_delay

        while self._running:
            try:
                async with websockets.connect(self.controller_url) as ws:
                    self._ws = ws
                    delay = self.reconnect_base_delay  # reset on successful connect
                    await self._session(ws)
            except (
                ConnectionError,
                OSError,
                websockets.exceptions.WebSocketException,
            ) as e:
                if not self._running:
                    break
                # If the server rejected us with 4002, stop immediately
                if (
                    isinstance(e, websockets.exceptions.ConnectionClosedError)
                    and e.rcvd is not None
                    and e.rcvd.code == 4002
                ):
                    logger.error(
                        f"Registration rejected: {e.rcvd.reason} — stopping agent"
                    )
                    break
                # 1012 = Service Restart — use fixed 10s retry interval
                if (
                    isinstance(e, websockets.exceptions.ConnectionClosedError)
                    and e.rcvd is not None
                    and e.rcvd.code == 1012
                ):
                    logger.warning("Server restarting (1012), retrying in 10s...")
                    await asyncio.sleep(10)
                    continue
                logger.warning(
                    f"Connection lost ({e}), reconnecting in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max_delay)
            except asyncio.CancelledError:
                break

        self._ws = None

    async def stop(self) -> None:
        """Stop the client and close the WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()

    async def send(self, msg: WSMessage) -> None:
        """Send a message over the WebSocket."""
        if self._ws:
            await self._ws.send(msg.model_dump_json())

    async def _session(self, ws: ClientConnection) -> None:
        """Run a single connected session: register, heartbeat, receive."""
        # Register
        reg = RegisterMessage(
            agent_name=self.agent_name,
            capabilities=self.capabilities,
        )
        await ws.send(reg.model_dump_json())

        # Wait for server-assigned agent ID
        raw = await ws.recv()
        ack = parse_message(raw)
        if not isinstance(ack, RegisterAckMessage):
            logger.error(f"Expected RegisterAck, got {type(ack).__name__}")
            return
        self.agent_id = ack.agent_id
        logger.info(f"Registered as {self.agent_name} (id={self.agent_id})")

        # Run heartbeat and receiver concurrently
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._heartbeat_loop(ws))
                tg.create_task(self._receive_loop(ws))
        except* websockets.exceptions.ConnectionClosed as eg:
            raise eg.exceptions[0]

    async def _heartbeat_loop(self, ws: ClientConnection) -> None:
        """Send periodic heartbeats."""
        while self._running:
            msg = HeartbeatMessage(agent_id=self.agent_id)
            await ws.send(msg.model_dump_json())
            await asyncio.sleep(self.heartbeat_interval)

    async def _receive_loop(self, ws: ClientConnection) -> None:
        """Receive and dispatch incoming messages from the controller."""
        async for raw in ws:
            msg = parse_message(raw)
            if isinstance(msg, DisconnectMessage):
                logger.info(f"Received disconnect: {msg.reason} — terminating")
                self._running = False
                await ws.close()
                return
            if self.on_message:
                await self.on_message(msg)
