from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone

import httpx
from concerto_shared.enums import Product
from loguru import logger
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Log,
    OptionList,
    Static,
)
from textual.widgets.option_list import Option

REFRESH_INTERVAL = 2.0  # seconds


class JobSubmitResult:
    """Result returned from the job submission screen."""

    def __init__(self, product: Product, duration: float | None) -> None:
        self.product = product
        self.duration = duration


class JobSubmitScreen(ModalScreen[JobSubmitResult | None]):
    """Modal dialog to select a product and set duration for a new job."""

    CSS = """
    JobSubmitScreen {
        align: center middle;
    }
    #picker-container {
        width: 55;
        height: auto;
        max-height: 24;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #picker-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #duration-label {
        margin-top: 1;
    }
    #duration-input {
        margin-bottom: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self._selected_product: Product | None = None

    def compose(self) -> ComposeResult:
        with Container(id="picker-container"):
            yield Label("Select product for new job:", id="picker-title")
            option_list = OptionList(id="product-options")
            for p in Product:
                option_list.add_option(Option(p.value, id=p.value))
            yield option_list
            yield Label(
                "Duration in seconds (leave empty for random):", id="duration-label"
            )
            yield Input(placeholder="e.g. 5.0", id="duration-input")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._selected_product = Product(event.option.id)
        self._try_submit()

    def _try_submit(self) -> None:
        if self._selected_product is None:
            return
        raw = self.query_one("#duration-input", Input).value.strip()
        duration: float | None = None
        if raw:
            try:
                duration = float(raw)
                if duration <= 0:
                    duration = None
            except ValueError:
                duration = None
        self.dismiss(JobSubmitResult(self._selected_product, duration))

    def action_cancel(self) -> None:
        self.dismiss(None)


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
        ("d", "remove_agent", "Remove Agent"),
        ("n", "new_job", "New Job"),
    ]

    def __init__(self, controller_url: str = "http://localhost:8000") -> None:
        super().__init__()
        self.controller_url = controller_url
        self._client = httpx.AsyncClient(base_url=controller_url, timeout=5.0)
        # Map row keys → agent IDs for the agents table
        self._agent_row_ids: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main"):
            with Container(id="agents-panel"):
                yield Static("Fleet Status", classes="panel-title")
                yield DataTable(id="agents-table", cursor_type="row")
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
        agents_table.add_columns(
            "Name", "Status", "Capabilities", "Current Job", "Last HB"
        )

        # Set up jobs table columns
        jobs_table = self.query_one("#jobs-table", DataTable)
        jobs_table.add_columns(
            "ID (short)", "Product", "Status", "Assigned To", "Created"
        )

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
        self._agent_row_ids.clear()

        status_colors = {
            "online": "green",
            "busy": "yellow",
            "offline": "red",
        }

        for agent in agents:
            status = agent["status"]
            color = status_colors.get(status, "white")
            caps = ", ".join(agent.get("capabilities", []))
            job_id = (
                str(agent.get("current_job_id", ""))[:8]
                if agent.get("current_job_id")
                else "—"
            )
            last_hb = agent.get("last_heartbeat", "—")
            if last_hb and last_hb != "—":
                try:
                    hb_time = datetime.fromisoformat(last_hb)
                    age = (datetime.now(timezone.utc) - hb_time).total_seconds()
                    last_hb = f"{age:.0f}s ago"
                except (ValueError, TypeError):
                    pass

            row_key = table.add_row(
                agent["name"],
                f"[{color}]{status}[/{color}]",
                caps,
                job_id,
                last_hb,
            )
            self._agent_row_ids[str(row_key)] = agent["id"]

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
            assigned = (
                str(job.get("assigned_agent_id", ""))[:8]
                if job.get("assigned_agent_id")
                else "—"
            )
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

    def action_remove_agent(self) -> None:
        """Remove the currently selected agent."""
        asyncio.create_task(self._remove_selected_agent())

    async def _remove_selected_agent(self) -> None:
        event_log = self.query_one("#event-log", Log)
        table = self.query_one("#agents-table", DataTable)

        if table.row_count == 0:
            event_log.write_line("[yellow]No agents to remove[/yellow]")
            return

        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        agent_id = self._agent_row_ids.get(str(row_key))
        if not agent_id:
            event_log.write_line("[yellow]No agent selected[/yellow]")
            return

        try:
            resp = await self._client.delete(f"/agents/{agent_id}")
            if resp.status_code == 204:
                event_log.write_line(f"[green]Agent {agent_id[:8]}… removed[/green]")
                await self._poll_data()
            else:
                event_log.write_line(
                    f"[red]Failed to remove agent: {resp.status_code}[/red]"
                )
        except Exception as e:
            event_log.write_line(f"[red]Error removing agent: {e}[/red]")

    def action_new_job(self) -> None:
        """Open job submission screen."""
        self.push_screen(JobSubmitScreen(), callback=self._on_job_submitted)

    def _on_job_submitted(self, result: JobSubmitResult | None) -> None:
        if result is not None:
            asyncio.create_task(self._submit_job(result.product, result.duration))

    async def _submit_job(self, product: Product, duration: float | None) -> None:
        event_log = self.query_one("#event-log", Log)
        try:
            payload: dict = {"product": product.value}
            if duration is not None:
                payload["duration"] = duration
            resp = await self._client.post("/jobs", json=payload)
            if resp.status_code == 201:
                job = resp.json()
                dur_str = f", duration={duration}s" if duration else ""
                event_log.write_line(
                    f"[green]Job {str(job['id'])[:8]}… submitted "
                    f"(product={product.value}{dur_str})[/green]"
                )
                await self._poll_data()
            else:
                event_log.write_line(
                    f"[red]Failed to submit job: {resp.status_code}[/red]"
                )
        except Exception as e:
            event_log.write_line(f"[red]Error submitting job: {e}[/red]")

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
