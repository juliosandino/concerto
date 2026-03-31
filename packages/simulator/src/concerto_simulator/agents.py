"""Agent lifecycle manager — creation, readiness checks, and cleanup."""

from __future__ import annotations

import asyncio
from types import TracebackType

import websockets
from concerto_agent.agent import ConcertoAgent
from concerto_shared.enums import AgentStatus, Product
from concerto_shared.messages import (
    DashboardRemoveAgentMessage,
    DashboardSnapshotMessage,
    parse_dashboard_message,
)
from loguru import logger

ALL_PRODUCTS = list(Product)

AGENT_NAMES = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
]


class AgentManager:
    """Manages the lifecycle of simulated agents."""

    def __init__(
        self,
        num_agents: int,
        controller_ws_url: str,
        ws: websockets.ClientConnection,
    ) -> None:
        """Initialize the manager with the number of agents to create and the controller WebSocket URL.

        :param num_agents: The number of agents to create and manage.
        :param controller_ws_url: The WebSocket URL of the controller to connect agents to.
        :param ws: An active WebSocket connection to the controller for receiving snapshots and sending cleanup
            messages.
        """
        self._controller_ws_url = controller_ws_url
        self._ws = ws
        self._agents: list[ConcertoAgent] = []
        self._tasks: list[asyncio.Task] = []

        for i in range(num_agents):
            name = f"sim-{AGENT_NAMES[i % len(AGENT_NAMES)]}-{i:03d}"
            agent = ConcertoAgent(
                agent_name=name,
                capabilities=ALL_PRODUCTS,
                controller_url=controller_ws_url,
            )
            self._agents.append(agent)

    @property
    def agents(self) -> list[ConcertoAgent]:
        """Get the list of managed agents."""
        return self._agents

    async def start(self) -> None:
        """Launch all agent run-loops as background tasks."""
        self._tasks = [asyncio.create_task(agent.run()) for agent in self._agents]
        logger.info(f"Started {len(self._agents)} agent tasks")

    async def wait_for_online(
        self,
        timeout: float = 30.0,
    ) -> None:
        """Wait for dashboard snapshots until every agent is ONLINE or BUSY.

        :param timeout: Maximum time to wait for all agents to be online before raising TimeoutError.
        """
        expected_names = {a.agent_name for a in self._agents}

        async with asyncio.timeout(timeout):
            while True:
                snapshot = await _wait_for_snapshot(self._ws)
                online_names = {
                    a.name
                    for a in snapshot.agents
                    if a.status in (AgentStatus.ONLINE, AgentStatus.BUSY)
                }
                if expected_names <= online_names:
                    logger.info(
                        f"All {len(self._agents)} agents are connected and online"
                    )
                    return

    async def cleanup(self) -> None:
        """Cancel agent tasks and remove agents from the controller."""
        for agent in self._agents:
            if agent.agent_id is None:
                continue
            try:
                msg = DashboardRemoveAgentMessage(agent_id=agent.agent_id)
                await self._ws.send(msg.model_dump_json())
                logger.info(f"Removed agent {agent.agent_name} ({agent.agent_id})")
            except websockets.exceptions.ConnectionClosed:
                logger.warning(
                    f"Cannot remove agent {agent.agent_name}: connection already closed"
                )

        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("All agent tasks stopped")

    async def __aenter__(self) -> AgentManager:
        await self.start()
        await self.wait_for_online()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.cleanup()


async def _wait_for_snapshot(
    ws: websockets.ClientConnection,
) -> DashboardSnapshotMessage:
    """Read frames until we get a DashboardSnapshotMessage."""
    async for raw in ws:
        msg = parse_dashboard_message(raw)
        if isinstance(msg, DashboardSnapshotMessage):
            return msg
    raise ConnectionError("WebSocket closed before snapshot received")
