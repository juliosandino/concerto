"""Typer CLI for the Concerto agent."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import typer
from concerto_agent.agent import ConcertoAgent
from concerto_shared.enums import Product
from loguru import logger

app = typer.Typer(help="Concerto agent — connects to the controller and executes jobs.")


def _parse_capabilities(value: str) -> list[Product]:
    """Parse capabilities from a JSON array or comma-separated string."""
    stripped = value.strip()
    if stripped.startswith("["):
        items = json.loads(stripped)
    else:
        items = [v.strip() for v in stripped.split(",") if v.strip()]
    return [Product(item) for item in items]


@app.command()
def run(
    agent_name: Annotated[
        str,
        typer.Option(
            "--agent-name",
            "-n",
            envvar="AGENT_AGENT_NAME",
            help="Unique name for this agent.",
        ),
    ] = "testbed-01",
    capabilities: Annotated[
        str,
        typer.Option(
            "--capability",
            "-p",
            envvar="AGENT_CAPABILITIES",
            help="Product capabilities (JSON array or comma-separated).",
        ),
    ] = "vehicle_gateway,asset_gateway",
    controller_url: Annotated[
        str,
        typer.Option(
            "--controller-url",
            "-u",
            envvar="AGENT_CONTROLLER_URL",
            help="WebSocket URL of the controller.",
        ),
    ] = "ws://localhost:8000/ws/agent",
    heartbeat_interval: Annotated[
        int,
        typer.Option(
            "--heartbeat-interval",
            envvar="AGENT_HEARTBEAT_INTERVAL_SEC",
            help="Seconds between heartbeats.",
        ),
    ] = 5,
    reconnect_base_delay: Annotated[
        float,
        typer.Option(
            "--reconnect-base-delay",
            envvar="AGENT_RECONNECT_BASE_DELAY_SEC",
            help="Initial reconnect backoff in seconds.",
        ),
    ] = 1.0,
    reconnect_max_delay: Annotated[
        float,
        typer.Option(
            "--reconnect-max-delay",
            envvar="AGENT_RECONNECT_MAX_DELAY_SEC",
            help="Maximum reconnect backoff in seconds.",
        ),
    ] = 30.0,
) -> None:
    """Start the agent, connecting to the controller."""
    parsed_capabilities = _parse_capabilities(capabilities)
    agent = ConcertoAgent(
        agent_name=agent_name,
        capabilities=parsed_capabilities,
        controller_url=controller_url,
        heartbeat_interval=heartbeat_interval,
        reconnect_base_delay=reconnect_base_delay,
        reconnect_max_delay=reconnect_max_delay,
    )
    logger.info(f"Agent {agent_name} starting (caps={parsed_capabilities})")
    asyncio.run(agent.run())
