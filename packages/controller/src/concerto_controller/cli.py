"""Unified CLI for the Concerto controller."""

from __future__ import annotations

from typing import Optional

import typer
import uvicorn
from alembic import command
from concerto_controller.config import settings
from concerto_controller.db.session import _alembic_cfg
from concerto_controller.mcp import ConcertoMCP

app = typer.Typer(help="Concerto TSS Controller CLI.")
db_app = typer.Typer(help="Database migration commands.")
app.add_typer(db_app, name="db")


@db_app.command()
def migrate() -> None:
    """Run alembic upgrade head."""
    command.upgrade(_alembic_cfg(), "head")


@db_app.command()
def revision(
    m: Optional[str] = typer.Option(
        "new migration", "--m", "-m", help="Revision message."
    ),
) -> None:
    """Generate a new auto-detected migration revision."""
    command.revision(_alembic_cfg(), message=m, autogenerate=True)


@db_app.command()
def downgrade(
    target: str = typer.Argument("-1", help="Revision target (e.g. -1, base)."),
) -> None:
    """Downgrade the database by one revision (or to a specific target)."""
    command.downgrade(_alembic_cfg(), target)


@app.command()
def run() -> None:
    """Start the controller server."""
    uvicorn.run(
        "concerto_controller.app:app",
        host=settings.ws_host,
        port=settings.ws_port,
        log_level="info",
    )


@app.command()
def mcp(
    controller_url: str = typer.Option(
        "ws://localhost:8000/ws/dashboard",
        "--controller-url",
        "-u",
        help="WebSocket URL of the controller dashboard endpoint.",
    ),
) -> None:
    """Start the MCP server for IDE integration."""
    ConcertoMCP(controller_url).run()


def main() -> None:
    """Entrypoint for the concerto-controller CLI."""
    app()
