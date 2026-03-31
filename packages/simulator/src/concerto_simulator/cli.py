"""Typer CLI for the Concerto fleet simulator."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from loguru import logger

app = typer.Typer(help="Concerto fleet simulator — spawn agents and queue jobs.")


@app.command()
def run(
    agents: Annotated[
        int, typer.Option("--agents", "-a", help="Number of agents to spawn")
    ] = 5,
    jobs: Annotated[
        int, typer.Option("--jobs", "-j", help="Number of jobs to queue")
    ] = 10,
    controller_url: Annotated[
        str, typer.Option(help="Controller agent WebSocket URL")
    ] = "ws://localhost:8000/ws/agent",
    dashboard_url: Annotated[
        str, typer.Option(help="Controller dashboard WebSocket URL")
    ] = "ws://localhost:8000/ws/dashboard",
    job_interval: Annotated[
        float, typer.Option(help="Seconds between job submissions")
    ] = 2.0,
) -> None:
    """Spawn simulated agents and queue jobs against the controller."""
    from concerto_simulator.simulator import run_simulation

    try:
        asyncio.run(
            run_simulation(
                num_agents=agents,
                num_jobs=jobs,
                controller_ws_url=controller_url,
                dashboard_ws_url=dashboard_url,
                job_interval=job_interval,
            )
        )
    except KeyboardInterrupt:
        logger.info("Simulator stopped")
