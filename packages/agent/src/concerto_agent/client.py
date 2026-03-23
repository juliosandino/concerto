from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Callable

import websockets
from websockets.asyncio.client import ClientConnection

from concerto_shared.enums import Product
from concerto_shared.messages import (
    HeartbeatMessage,
    RegisterMessage,
    WSMessage,
    parse_message,
)

logger = logging.getLogger(__name__)


class AgentClient:
    """WebSocket client that connects to the controller, registers, and
    maintains a heartbeat loop while dispatching incoming messages."""

    def __init__(
        self,
        agent_id: uuid.UUID,
        agent_name: str,
        capabilities: list[Product],
        controller_url: str,
        heartbeat_interval: float = 5.0,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
        on_message: Callable[[WSMessage], asyncio.Future] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.capabilities = capabilities
        self.controller_url = controller_url
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.on_message = on_message
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
            except (ConnectionError, OSError, websockets.exceptions.WebSocketException) as e:
                if not self._running:
                    break
                logger.warning("Connection lost (%s), reconnecting in %.1fs...", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.reconnect_max_delay)
            except asyncio.CancelledError:
                break

        self._ws = None

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()

    async def send(self, msg: WSMessage) -> None:
        if self._ws:
            await self._ws.send(msg.model_dump_json())

    async def _session(self, ws: ClientConnection) -> None:
        """Run a single connected session: register, heartbeat, receive."""
        # Register
        reg = RegisterMessage(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            capabilities=self.capabilities,
        )
        await ws.send(reg.model_dump_json())
        logger.info("Registered as %s (%s)", self.agent_name, self.agent_id)

        # Run heartbeat and receiver concurrently
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_loop(ws))
            tg.create_task(self._receive_loop(ws))

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
            if self.on_message:
                await self.on_message(msg)
