"""WebSocket client for connecting agents to the controller."""

from __future__ import annotations

import asyncio
import uuid
from typing import Callable
from unittest import case

import websockets
from concerto_agent.executor import execute_job
from concerto_shared.enums import Product
from concerto_shared.messages import (
    DisconnectMessage,
    HeartbeatMessage,
    JobAssignMessage,
    RegisterAckMessage,
    RegisterMessage,
    WSMessage,
    parse_message,
)
from loguru import logger
from websockets.asyncio.client import ClientConnection


class ConcertoAgent:
    """WebSocket client that connects to the controller, registers, and maintains a heartbeat loop while dispatching
    incoming messages."""

    CONNECTION_REJECTED = 4002
    SERVICE_RESTART = 1012

    def __init__(
        self,
        agent_name: str,
        capabilities: list[Product],
        controller_url: str,
        heartbeat_interval: float = 5.0,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 30.0,
    ) -> None:
        self.agent_name = agent_name
        self.capabilities = capabilities
        self.controller_url = controller_url
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_base_delay = reconnect_base_delay
        self.reconnect_max_delay = reconnect_max_delay
        self.agent_id: uuid.UUID | None = None
        self._ws: ClientConnection | None = None
        self._running = False

    async def run(self) -> None:
        """Connect with automatic reconnection using exponential backoff."""
        self._running = True
        delay = self.reconnect_base_delay

        while self._running:
            try:
                try:
                    async with websockets.connect(self.controller_url) as ws:
                        self._ws = ws
                        delay = self.reconnect_base_delay  # reset on successful connect
                        await self._session()
                # Handle different disconnect scenarios with specific logging and backoff behavior
                except websockets.exceptions.ConnectionClosedError as err:
                    if err.rcvd is None:
                        logger.error(f"Connection closed with no close frame: {err}")
                        break

                    match err.rcvd.code:
                        # If the server rejected us with 4002, stop immediately
                        case self.CONNECTION_REJECTED:
                            logger.error(
                                f"Registration rejected: {err.rcvd.reason} — stopping agent"
                            )
                            break
                        # 1012 = Service Restart — use retry interval
                        case self.SERVICE_RESTART:
                            logger.warning(
                                f"Server restarting (1012), retrying in {delay:.1f}s..."
                            )
                            await asyncio.sleep(delay)
                            delay = min(delay * 2, self.reconnect_max_delay)
                            continue
                        # With unexpected code or no code, log and stop
                        case _:
                            logger.error(
                                f"Connection closed with code {err.rcvd.code}: {err.rcvd.reason} — stopping agent"
                            )
                            break
                # Handle connection refused (e.g. server not up yet) with backoff retries
                except ConnectionRefusedError:
                    logger.warning(f"Connection refused, retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.reconnect_max_delay)

            # Handle cancellation (e.g. from shutdown signal) gracefully
            except asyncio.CancelledError:
                break

        self._ws = None

    async def stop(self, msg: DisconnectMessage) -> None:
        """Stop the client and close the WebSocket."""
        logger.info(f"Received disconnect: {msg.reason} — terminating")
        self._running = False
        if self._ws:
            await self._ws.close()

    async def send(self, msg: WSMessage) -> None:
        """Send a message over the WebSocket."""
        if self._ws:
            await self._ws.send(msg.model_dump_json())

    async def _session(self) -> None:
        """Run a single connected session: register, heartbeat, receive."""
        # Register
        register_msg = RegisterMessage(
            agent_name=self.agent_name,
            capabilities=self.capabilities,
        )
        await self.send(register_msg)

        # Wait for server-assigned agent ID
        raw = await self._ws.recv()
        ack = parse_message(raw)
        match ack:
            case RegisterAckMessage():
                self.agent_id = ack.agent_id
                logger.info(f"Registered as {self.agent_name} (id={self.agent_id})")
            case _:
                logger.error(f"Expected RegisterAck, got {type(ack).__name__}")
                return

        # Run heartbeat and receiver concurrently
        try:
            async with asyncio.TaskGroup() as task_group:
                task_group.create_task(self._heartbeat_loop())
                task_group.create_task(self._receive_loop())
        except* websockets.exceptions.ConnectionClosed as eg:
            raise eg.exceptions[0]

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._running:
            msg = HeartbeatMessage(agent_id=self.agent_id)
            await self.send(msg)
            await asyncio.sleep(self.heartbeat_interval)

    async def _receive_loop(self) -> None:
        """Receive and dispatch incoming messages from the controller."""
        async for raw in self._ws:
            msg = parse_message(raw)
            match msg:
                case DisconnectMessage():
                    await self.stop(msg)
                    return
                case JobAssignMessage():
                    asyncio.create_task(
                        execute_job(
                            agent_id=self.agent_id,
                            assignment=msg,
                            send_fn=self.send,
                        )
                    )
                case _:
                    logger.warning(
                        f"Received unrecognized message type: {type(msg).__name__}"
                    )
