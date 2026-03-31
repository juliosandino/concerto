"""Dashboard command/action handlers."""

from __future__ import annotations

from concerto_dashboard.ws_client import DashboardWSClient
from concerto_shared.enums import Product
from concerto_shared.messages import (
    DashboardCreateJobMessage,
    DashboardRemoveAgentMessage,
)
from textual.widgets import DataTable, RichLog


async def remove_selected_agent(
    agents_table: DataTable,
    agent_row_ids: dict[str, str],
    ws_client: DashboardWSClient,
    event_log: RichLog,
) -> None:
    """Remove the agent currently highlighted in the agents table.

    :param agents_table: The DataTable widget displaying agents.
    :param agent_row_ids: Mapping of DataTable row keys to agent IDs.
    :param ws_client: The WebSocket client to send the remove command.
    :param event_log: The RichLog widget to write status messages to.
    """
    if agents_table.row_count == 0:
        event_log.write("[yellow]No agents to remove[/yellow]")
        return

    row_key = agents_table.coordinate_to_cell_key(
        agents_table.cursor_coordinate
    ).row_key
    agent_id = agent_row_ids.get(str(row_key))
    if not agent_id:
        event_log.write("[yellow]No agent selected[/yellow]")
        return

    event_log.write(f"Removing agent {agent_id[:8]}…")
    await ws_client.send(DashboardRemoveAgentMessage(agent_id=agent_id))


async def submit_job(
    product: Product,
    duration: float | None,
    ws_client: DashboardWSClient,
    event_log: RichLog,
) -> None:
    """Submit a new job to the controller.

    :param product: The product to run the job for.
    :param duration: Optional duration hint for the job.
    :param ws_client: The WebSocket client to send the create command.
    :param event_log: The RichLog widget to write status messages to.
    """
    dur_str = f", duration={duration}s" if duration else ""
    event_log.write(f"Submitting job (product={product.value}{dur_str})…")
    await ws_client.send(DashboardCreateJobMessage(product=product, duration=duration))
