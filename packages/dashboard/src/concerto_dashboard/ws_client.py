"""WebSocket client for the dashboard-to-controller connection."""

from __future__ import annotations

import asyncio
from typing import Callable

import websockets
from concerto_shared.messages import DashboardSnapshotMessage, parse_dashboard_message
from loguru import logger
from pydantic import BaseModel


class DashboardWSClient:
    """Manages the persistent WebSocket connection to the controller."""

    def __init__(
        self,
        url: str,
        on_snapshot: Callable[[DashboardSnapshotMessage], None],
        on_log: Callable[[str], None],
    ) -> None:
        self._url = url
        self._on_snapshot = on_snapshot
        self._on_log = on_log
        self._ws: websockets.ClientConnection | None = None
        self._task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        """Whether the WebSocket connection is currently active."""
        return self._ws is not None

    def start(self) -> None:
        """Start the WebSocket connection loop as a background task."""
        self._task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self) -> None:
        """Maintain a persistent WebSocket connection with reconnection."""
        backoff = 1.0
        max_backoff = 30.0

        while True:
            try:
                async with websockets.connect(self._url) as ws:
                    self._ws = ws
                    backoff = 1.0
                    self._on_log("[green]Connected to controller[/green]")

                    async for raw in ws:
                        try:
                            msg = parse_dashboard_message(raw)
                            match msg:
                                case DashboardSnapshotMessage():
                                    self._on_snapshot(msg)
                        except Exception as exc:
                            logger.warning(f"Bad dashboard message: {exc}")

            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._ws = None
                self._on_log(
                    f"[red]Connection lost ({exc}), retrying in {backoff:.0f}s…[/red]"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def send(self, msg: BaseModel) -> None:
        """Send a Pydantic message over the WebSocket.

        :param msg: The Pydantic BaseModel message to send.
        """
        if self._ws is None:
            self._on_log("[red]Not connected to controller[/red]")
            return
        try:
            await self._ws.send(msg.model_dump_json())
        except Exception as exc:
            self._on_log(f"[red]Send error: {exc}[/red]")

    async def close(self) -> None:
        """Cancel the connection loop and close the WebSocket."""
        # Cancel the connection loop task
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Close the WebSocket connection if open
        if self._ws:
            await self._ws.close()
