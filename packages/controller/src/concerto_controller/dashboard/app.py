from __future__ import annotations

import asyncio
import argparse
import logging
from datetime import datetime, timezone

import httpx
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Log, Static

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 2.0  # seconds


class ConcertoDashboard(App):
    """Textual TUI dashboard for Concerto TSS fleet visibility."""

    CSS = """
    #main {
        layout: grid;
        grid-size: 2 2;
        grid-rows: 1fr 1fr;
        grid-columns: 1fr 1fr;
    }
    #agents-panel {
        row-span: 1;
        column-span: 1;
        border: solid green;
    }
    #jobs-panel {
        row-span: 1;
        column-span: 1;
        border: solid cyan;
    }
    #stats-panel {
        row-span: 1;
        column-span: 1;
        border: solid yellow;
    }
    #log-panel {
        row-span: 1;
        column-span: 1;
        border: solid magenta;
    }
    DataTable {
        height: 100%;
    }
    .panel-title {
        text-style: bold;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, controller_url: str = "http://localhost:8000") -> None:
        super().__init__()
        self.controller_url = controller_url
        self._client = httpx.AsyncClient(base_url=controller_url, timeout=5.0)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            with Container(id="agents-panel"):
                yield Static("Fleet Status", classes="panel-title")
                yield DataTable(id="agents-table")
            with Container(id="jobs-panel"):
                yield Static("Job Queue", classes="panel-title")
                yield DataTable(id="jobs-table")
            with Container(id="stats-panel"):
                yield Static("Statistics", classes="panel-title")
                yield Static(id="stats-content")
            with Container(id="log-panel"):
                yield Static("Event Log", classes="panel-title")
                yield Log(id="event-log")
        yield Footer()

    async def on_mount(self) -> None:
        # Set up agent table columns
        agents_table = self.query_one("#agents-table", DataTable)
        agents_table.add_columns("Name", "Status", "Capabilities", "Current Job", "Last HB")

        # Set up jobs table columns
        jobs_table = self.query_one("#jobs-table", DataTable)
        jobs_table.add_columns("ID (short)", "Product", "Status", "Assigned To", "Created")

        # Start polling
        self.set_interval(REFRESH_INTERVAL, self._poll_data)
        await self._poll_data()

    async def _poll_data(self) -> None:
        event_log = self.query_one("#event-log", Log)
        try:
            await self._refresh_agents()
            await self._refresh_jobs()
            await self._refresh_stats()
        except httpx.ConnectError:
            event_log.write_line("[red]Cannot connect to controller[/red]")
        except Exception as e:
            event_log.write_line(f"[red]Error: {e}[/red]")

    async def _refresh_agents(self) -> None:
        resp = await self._client.get("/agents")
        resp.raise_for_status()
        agents = resp.json()

        table = self.query_one("#agents-table", DataTable)
        table.clear()

        status_colors = {
            "online": "green",
            "busy": "yellow",
            "offline": "red",
        }

        for agent in agents:
            status = agent["status"]
            color = status_colors.get(status, "white")
            caps = ", ".join(agent.get("capabilities", []))
            job_id = str(agent.get("current_job_id", ""))[:8] if agent.get("current_job_id") else "—"
            last_hb = agent.get("last_heartbeat", "—")
            if last_hb and last_hb != "—":
                try:
                    hb_time = datetime.fromisoformat(last_hb)
                    age = (datetime.now(timezone.utc) - hb_time).total_seconds()
                    last_hb = f"{age:.0f}s ago"
                except (ValueError, TypeError):
                    pass

            table.add_row(
                agent["name"],
                f"[{color}]{status}[/{color}]",
                caps,
                job_id,
                last_hb,
            )

    async def _refresh_jobs(self) -> None:
        resp = await self._client.get("/jobs")
        resp.raise_for_status()
        jobs = resp.json()

        table = self.query_one("#jobs-table", DataTable)
        table.clear()

        status_colors = {
            "queued": "white",
            "assigned": "cyan",
            "running": "yellow",
            "completed": "green",
            "failed": "red",
        }

        for job in jobs[:50]:  # Show most recent 50
            status = job["status"]
            color = status_colors.get(status, "white")
            short_id = str(job["id"])[:8]
            assigned = str(job.get("assigned_agent_id", ""))[:8] if job.get("assigned_agent_id") else "—"
            created = job.get("created_at", "—")
            if created != "—":
                try:
                    created = datetime.fromisoformat(created).strftime("%H:%M:%S")
                except (ValueError, TypeError):
                    pass

            table.add_row(
                short_id,
                job["product"],
                f"[{color}]{status}[/{color}]",
                assigned,
                created,
            )

    async def _refresh_stats(self) -> None:
        agents_resp = await self._client.get("/agents")
        jobs_resp = await self._client.get("/jobs")
        agents = agents_resp.json()
        jobs = jobs_resp.json()

        online = sum(1 for a in agents if a["status"] == "online")
        busy = sum(1 for a in agents if a["status"] == "busy")
        offline = sum(1 for a in agents if a["status"] == "offline")
        queued = sum(1 for j in jobs if j["status"] == "queued")
        running = sum(1 for j in jobs if j["status"] == "running")
        completed = sum(1 for j in jobs if j["status"] == "completed")
        failed = sum(1 for j in jobs if j["status"] == "failed")

        stats_text = (
            f"[bold]Agents:[/bold]  [green]{online} online[/green]  "
            f"[yellow]{busy} busy[/yellow]  [red]{offline} offline[/red]\n"
            f"[bold]Jobs:[/bold]    {queued} queued  [yellow]{running} running[/yellow]  "
            f"[green]{completed} done[/green]  [red]{failed} failed[/red]\n"
            f"[bold]Total:[/bold]   {len(agents)} agents  {len(jobs)} jobs"
        )
        self.query_one("#stats-content", Static).update(stats_text)

    def action_refresh(self) -> None:
        asyncio.create_task(self._poll_data())

    async def on_unmount(self) -> None:
        await self._client.aclose()


def run() -> None:
    parser = argparse.ArgumentParser(description="Concerto TUI Dashboard")
    parser.add_argument(
        "--controller-url",
        default="http://localhost:8000",
        help="Controller REST API URL",
    )
    args = parser.parse_args()

    app = ConcertoDashboard(controller_url=args.controller_url)
    app.run()


if __name__ == "__main__":
    run()
