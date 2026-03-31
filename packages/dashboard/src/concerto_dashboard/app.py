"""Textual TUI dashboard application for Concerto TSS."""

from __future__ import annotations

import asyncio

from concerto_dashboard.commands import remove_selected_agent, submit_job
from concerto_dashboard.screens import JobSubmitResult, JobSubmitScreen
from concerto_dashboard.state import apply_snapshot
from concerto_dashboard.ws_client import DashboardWSClient
from concerto_shared.messages import DashboardSnapshotMessage
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, RichLog, Static


class ConcertoDashboard(App):
    """Textual TUI dashboard for Concerto TSS fleet visibility."""

    CSS_PATH = "dashboard.tcss"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("d", "remove_agent", "Remove Agent"),
        ("n", "new_job", "New Job"),
    ]

    def __init__(
        self, controller_ws_url: str = "ws://localhost:8000/ws/dashboard"
    ) -> None:
        super().__init__()
        self._ws_client = DashboardWSClient(
            url=controller_ws_url,
            on_snapshot=self._on_snapshot,
            on_log=self._on_log,
        )
        self._agent_row_ids: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        """Build the widget tree."""
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
                yield RichLog(id="event-log", markup=True)
        yield Footer()

    async def on_mount(self) -> None:
        """Initialize tables and start the WebSocket loop."""
        agents_table = self.query_one("#agents-table", DataTable)
        agents_table.add_columns(
            "Name", "Status", "Capabilities", "Current Job", "Last HB"
        )

        jobs_table = self.query_one("#jobs-table", DataTable)
        jobs_table.add_columns(
            "ID (short)", "Product", "Status", "Assigned To", "Created"
        )

        self._ws_client.start()

    # ------------------------------------------------------------------
    # Callbacks wired to DashboardWSClient
    # ------------------------------------------------------------------

    def _on_snapshot(self, snapshot: DashboardSnapshotMessage) -> None:
        """Apply a new snapshot to refresh all dashboard panels.

        :param snapshot: The DashboardSnapshotMessage containing the latest state.
        """
        apply_snapshot(
            snapshot,
            agents_table=self.query_one("#agents-table", DataTable),
            jobs_table=self.query_one("#jobs-table", DataTable),
            stats_widget=self.query_one("#stats-content", Static),
            agent_row_ids=self._agent_row_ids,
        )

    def _on_log(self, text: str) -> None:
        """Handle log messages from the WebSocket client.

        :param text: The log message text.
        """
        self.query_one("#event-log", RichLog).write(text)

    # ------------------------------------------------------------------
    # Keybinding actions
    # ------------------------------------------------------------------

    def action_remove_agent(self) -> None:
        """Remove the currently selected agent."""
        asyncio.create_task(
            remove_selected_agent(
                agents_table=self.query_one("#agents-table", DataTable),
                agent_row_ids=self._agent_row_ids,
                ws_client=self._ws_client,
                event_log=self.query_one("#event-log", RichLog),
            )
        )

    def action_new_job(self) -> None:
        """Open job submission screen."""
        self.push_screen(JobSubmitScreen(), callback=self._on_job_submitted)

    def _on_job_submitted(self, result: JobSubmitResult | None) -> None:
        """Handle the result from the job submission screen.

        :param result: The JobSubmitResult containing the selected product and duration or None if the submission was
            cancelled.
        """
        if result is not None:
            asyncio.create_task(
                submit_job(
                    product=result.product,
                    duration=result.duration,
                    ws_client=self._ws_client,
                    event_log=self.query_one("#event-log", RichLog),
                )
            )

    async def on_unmount(self) -> None:
        """Cancel WebSocket task and close the connection."""
        await self._ws_client.close()
