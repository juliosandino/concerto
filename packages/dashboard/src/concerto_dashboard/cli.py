"""CLI entry point for the Concerto TUI Dashboard."""

from typing import Annotated

import typer
from concerto_dashboard.app import ConcertoDashboard

app = typer.Typer(help="Concerto TUI Dashboard")


@app.command()
def run(
    controller_url: Annotated[
        str,
        typer.Option(help="Controller WebSocket URL"),
    ] = "ws://localhost:8000/ws/dashboard",
) -> None:
    """Launch the Concerto TUI dashboard."""
    dashboard = ConcertoDashboard(controller_ws_url=controller_url)
    dashboard.run()
