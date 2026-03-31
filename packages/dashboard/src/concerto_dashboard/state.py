"""State update logic for dashboard panels."""

from __future__ import annotations

from datetime import datetime, timezone

from concerto_shared.enums import AgentStatus, JobStatus
from concerto_shared.messages import DashboardSnapshotMessage
from concerto_shared.models import AgentInfo, JobInfo
from textual.widgets import DataTable, Static

AGENT_STATUS_COLORS: dict[AgentStatus, str] = {
    AgentStatus.ONLINE: "green",
    AgentStatus.BUSY: "yellow",
    AgentStatus.OFFLINE: "red",
}

JOB_STATUS_COLORS: dict[JobStatus, str] = {
    JobStatus.QUEUED: "white",
    JobStatus.ASSIGNED: "cyan",
    JobStatus.RUNNING: "yellow",
    JobStatus.COMPLETED: "green",
    JobStatus.PASSED: "green",
    JobStatus.FAILED: "red",
}


def update_agents_table(
    table: DataTable,
    agents: list[AgentInfo],
    agent_row_ids: dict[str, str],
) -> None:
    """Refresh the agents DataTable from the latest snapshot."""
    table.clear()
    agent_row_ids.clear()

    for agent in agents:
        color = AGENT_STATUS_COLORS.get(agent.status, "white")
        caps = ", ".join(c.value for c in agent.capabilities)
        job_id = str(agent.current_job_id)[:8] if agent.current_job_id else "\u2014"
        if agent.last_heartbeat:
            age = (datetime.now(timezone.utc) - agent.last_heartbeat).total_seconds()
            last_hb = f"{age:.0f}s ago"
        else:
            last_hb = "\u2014"

        row_key = table.add_row(
            agent.name,
            f"[{color}]{agent.status.value}[/{color}]",
            caps,
            job_id,
            last_hb,
        )
        agent_row_ids[str(row_key)] = str(agent.id)


def update_jobs_table(table: DataTable, jobs: list[JobInfo]) -> None:
    """Refresh the jobs DataTable from the latest snapshot."""
    table.clear()

    for job in jobs[:50]:
        color = JOB_STATUS_COLORS.get(job.status, "white")
        short_id = str(job.id)[:8]
        assigned = str(job.assigned_agent_id)[:8] if job.assigned_agent_id else "\u2014"
        created = job.created_at.strftime("%H:%M:%S") if job.created_at else "\u2014"

        table.add_row(
            short_id,
            job.product.value,
            f"[{color}]{job.status.value}[/{color}]",
            assigned,
            created,
        )


def update_stats(
    stats_widget: Static,
    agents: list[AgentInfo],
    jobs: list[JobInfo],
) -> None:
    """Refresh the statistics panel from the latest snapshot.

    :param stats_widget: The Static widget to update with stats text.
    :param agents: The list of AgentInfo objects from the snapshot.
    :param jobs: The list of JobInfo objects from the snapshot.
    """
    online = sum(1 for a in agents if a.status == AgentStatus.ONLINE)
    busy = sum(1 for a in agents if a.status == AgentStatus.BUSY)
    offline = sum(1 for a in agents if a.status == AgentStatus.OFFLINE)
    queued = sum(1 for j in jobs if j.status == JobStatus.QUEUED)
    running = sum(1 for j in jobs if j.status == JobStatus.RUNNING)
    completed = sum(
        1 for j in jobs if j.status in (JobStatus.COMPLETED, JobStatus.PASSED)
    )
    failed = sum(1 for j in jobs if j.status == JobStatus.FAILED)

    stats_text = (
        f"[bold]Agents:[/bold]  [green]{online} online[/green]  "
        f"[yellow]{busy} busy[/yellow]  [red]{offline} offline[/red]\n"
        f"[bold]Jobs:[/bold]    {queued} queued  [yellow]{running} running[/yellow]  "
        f"[green]{completed} done[/green]  [red]{failed} failed[/red]\n"
        f"[bold]Total:[/bold]   {len(agents)} agents  {len(jobs)} jobs"
    )
    stats_widget.update(stats_text)


def apply_snapshot(
    snapshot: DashboardSnapshotMessage,
    agents_table: DataTable,
    jobs_table: DataTable,
    stats_widget: Static,
    agent_row_ids: dict[str, str],
) -> None:
    """Apply a full snapshot to all dashboard panels.

    :param snapshot: The DashboardSnapshotMessage containing the latest state.
    :param agents_table: The DataTable widget displaying agents.
    :param jobs_table: The DataTable widget displaying jobs.
    :param stats_widget: The Static widget displaying statistics.
    :param agent_row_ids: Mapping of DataTable row keys to agent IDs, updated by
    """
    update_agents_table(agents_table, snapshot.agents, agent_row_ids)
    update_jobs_table(jobs_table, snapshot.jobs)
    update_stats(stats_widget, snapshot.agents, snapshot.jobs)
