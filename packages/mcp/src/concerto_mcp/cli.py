"""Typer CLI for the Concerto MCP server."""

from __future__ import annotations

from typing import Annotated

import typer
from concerto_mcp.server import ConcertoMCP

app = typer.Typer(
    help="Concerto MCP server — exposes controller REST API as MCP tools."
)


@app.callback(invoke_without_command=True)
def run(
    controller_url: Annotated[
        str,
        typer.Option(
            "--controller-url",
            "-u",
            envvar="CONCERTO_CONTROLLER_URL",
            help="Base HTTP URL of the Concerto controller.",
        ),
    ] = "http://localhost:8000",
) -> None:
    """Start the MCP server over stdio."""
    ConcertoMCP(controller_url).run()
