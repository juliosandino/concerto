"""MCP server for the Concerto controller — exposes job and agent tools via the dashboard WebSocket."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import websockets
from concerto_shared.enums import Product
from concerto_shared.messages import (
    DashboardCreateJobMessage,
    DashboardSnapshotMessage,
    parse_dashboard_message,
)
from fastmcp import FastMCP
from loguru import logger


class ControllerConnection:
    """Manages the WebSocket connection to the controller and caches state snapshots."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: websockets.ClientConnection | None = None
        self._snapshot: DashboardSnapshotMessage | None = None
        self._snapshot_event: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._last_error: str | None = None

    @property
    def snapshot(self) -> DashboardSnapshotMessage | None:
        """Get the latest dashboard snapshot received from the controller."""
        return self._snapshot

    @property
    def connected(self) -> bool:
        """Check if the controller is connected."""
        return self._ws is not None

    @property
    def last_error(self) -> str | None:
        """Get the most recent connection or message parsing error."""
        return self._last_error

    async def start(self) -> None:
        """Start the background listener task."""
        logger.info(f"Starting controller connection to {self._url}")
        self._task = asyncio.create_task(self._listen())
        # Wait for the first snapshot instead of a fixed sleep
        try:
            await asyncio.wait_for(self._snapshot_event.wait(), timeout=5.0)
            logger.info("Initial snapshot received")
        except TimeoutError:
            logger.warning(
                f"No dashboard snapshot received within 5 seconds from {self._url}"
            )

    async def stop(self) -> None:
        """Cancel the listener and clean up."""
        logger.info("Stopping controller connection")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Controller connection stopped")

    async def send(self, message: str) -> None:
        """Send a text message over the WebSocket."""
        if self._ws is None:
            logger.error("Attempted to send message but WebSocket is not connected")
            raise ConnectionError("Not connected to the controller")
        logger.debug(f"Sending message: {message}")
        await self._ws.send(message)

    def _handle_message(self, raw: str | bytes) -> None:
        """Parse a single WebSocket message and update the snapshot cache."""
        msg = parse_dashboard_message(raw)
        logger.debug(f"Parsed message type: {type(msg).__name__}")
        if isinstance(msg, DashboardSnapshotMessage):
            self._snapshot = msg
            self._snapshot_event.set()
            logger.debug(
                f"Snapshot updated: {len(msg.agents)} agents, {len(msg.jobs)} jobs"
            )

    async def _listen(self) -> None:
        """Maintain a persistent WebSocket connection and cache snapshots."""
        backoff = 1.0
        while True:
            try:
                await self._connect_and_receive()
                backoff = 1.0
            except asyncio.CancelledError:
                logger.info("Listener task cancelled")
                return
            except Exception as exc:
                self._last_error = f"WebSocket listener error: {exc}"
                logger.exception(
                    f"Controller WebSocket error (reconnecting in {backoff:.1f}s)"
                )
            finally:
                self._ws = None
                self._snapshot_event.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    async def _connect_and_receive(self) -> None:
        """Open a WebSocket connection and process messages until disconnected."""
        logger.info(f"Connecting to controller WebSocket at {self._url}")
        async with websockets.connect(self._url) as ws:
            self._ws = ws
            self._last_error = None
            logger.info(f"WebSocket connected to {self._url}")
            async for raw in ws:
                logger.debug(f"Received raw message ({len(raw)} bytes)")
                try:
                    self._handle_message(raw)
                except Exception as exc:
                    self._last_error = f"Failed to parse dashboard message: {exc}"
                    logger.exception("Failed to parse dashboard message")


class ConcertoMCP:
    """Wraps the FastMCP server and controller connection."""

    def __init__(
        self, controller_url: str = "ws://localhost:8000/ws/dashboard"
    ) -> None:
        """Initialize the MCP server and controller connection.

        :param controller_url: The WebSocket URL of the controller dashboard endpoint.
            Defaults to ws://localhost:8000/ws/dashboard.

        """
        self._conn = ControllerConnection(controller_url)
        self._mcp = FastMCP("Concerto Controller", lifespan=self._lifespan)
        self._register_tools()
        logger.info(f"ConcertoMCP initialized with controller URL: {controller_url}")

    @asynccontextmanager
    async def _lifespan(self, mcp: FastMCP):  # pylint: disable=unused-argument
        """Manage the lifespan of the MCP server.

        :param mcp: The FastMCP instance (injected by FastMCP on startup).
        """
        logger.info("MCP server starting up")
        await self._conn.start()
        yield
        await self._conn.stop()
        logger.info("MCP server shut down")

    def _register_tools(self) -> None:
        """Register MCP tools for interacting with the controller."""
        conn = self._conn

        @self._mcp.tool()
        async def queue_job(product: Product, duration: float | None = None) -> str:
            """Queue a new test job for the specified product.

            :param product: The product to test.
            :param duration: Optional job duration in seconds.
            """
            logger.info(f"queue_job called: product={product}, duration={duration}")
            if not conn.connected:
                logger.warning("queue_job failed: not connected to controller")
                return "Error: not connected to the controller"

            msg = DashboardCreateJobMessage(product=product, duration=duration)
            await conn.send(msg.model_dump_json())
            logger.info(f"Job queued for product '{product}'")

            return f"Job queued for product '{product}'" + (
                f" with duration {duration}s" if duration else ""
            )

        @self._mcp.tool()
        async def list_jobs() -> list[dict]:
            """List all current jobs with their status, product, and assignment info."""
            logger.info("list_jobs called")
            snap = conn.snapshot
            if snap is None:
                logger.warning(
                    f"list_jobs: no snapshot available (connected={conn.connected}, last_error={conn.last_error})"
                )
                return [
                    {
                        "error": "No snapshot received yet — is the controller running?",
                        "connected": conn.connected,
                        "last_error": conn.last_error,
                    }
                ]
            logger.info(f"list_jobs returning {len(snap.jobs)} jobs")
            return [job.model_dump(mode="json") for job in snap.jobs]

        @self._mcp.tool()
        async def list_agents() -> list[dict]:
            """List all registered agents with their status, capabilities, and current job."""
            logger.info("list_agents called")
            logger.info(f"conn object id: {id(conn)}")
            logger.info(f"conn.connected: {conn.connected}")
            logger.info(f"conn.snapshot is None: {conn.snapshot is None}")
            logger.info(f"conn._last_error: {conn.last_error}")
            snap = conn.snapshot
            if snap is None:
                logger.warning(
                    f"list_agents: no snapshot available (connected={conn.connected}, last_error={conn.last_error})"
                )
                return [
                    {
                        "error": "No snapshot received yet — is the controller running?",
                        "connected": conn.connected,
                        "last_error": conn.last_error,
                    }
                ]
            logger.info(f"list_agents returning {len(snap.agents)} agents")
            return [agent.model_dump(mode="json") for agent in snap.agents]

    def run(self) -> None:
        """Start the MCP server over stdio."""
        self._mcp.run(transport="stdio")
