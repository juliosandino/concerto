"""Typer CLI for the Concerto agent."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from concerto_agent.agent import ConcertoAgent
from concerto_agent.config import load_settings
from loguru import logger

app = typer.Typer(help="Concerto agent — connects to the controller and executes jobs.")


@app.command()
def run(
    config: Annotated[
        str | None,
        typer.Option(
            "--config",
            "-c",
            help="Path to a YAML config file (agent_name, capabilities)",
        ),
    ] = None,
) -> None:
    """Start the agent, connecting to the controller."""
    settings = load_settings(config)
    agent = ConcertoAgent(
        agent_name=settings.agent_name,
        capabilities=settings.capabilities,
        controller_url=settings.controller_url,
        heartbeat_interval=settings.heartbeat_interval_sec,
        reconnect_base_delay=settings.reconnect_base_delay_sec,
        reconnect_max_delay=settings.reconnect_max_delay_sec,
    )
    logger.info(f"Agent {settings.agent_name} starting (caps={settings.capabilities})")
    asyncio.run(agent.run())
