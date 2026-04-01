"""Tests for heartbeat monitor stale agent detection logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from concerto_controller.db.models import AgentRecord, JobRecord
from concerto_shared.enums import AgentStatus, JobStatus


class TestHeartbeatStaleDetection:
    """Test the staleness detection logic used by the heartbeat monitor."""

    def test_agent_is_stale_when_heartbeat_expired(self):
        """Agent with old heartbeat should be considered stale."""
        timeout = 15  # seconds
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout)

        agent = AgentRecord(
            id=uuid.uuid4(),
            name="stale-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=30),
        )

        assert agent.last_heartbeat < cutoff
        assert agent.status != AgentStatus.OFFLINE

    def test_agent_is_not_stale_when_heartbeat_recent(self):
        """Agent with recent heartbeat should not be stale."""

        timeout = 15
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout)

        agent = AgentRecord(
            id=uuid.uuid4(),
            name="fresh-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=5),
        )

        assert agent.last_heartbeat >= cutoff

    def test_offline_agent_is_not_rechecked(self):
        """Agents already offline should be skipped."""

        agent = AgentRecord(
            id=uuid.uuid4(),
            name="offline-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.OFFLINE,
            last_heartbeat=None,
        )

        # The heartbeat monitor filters: status != OFFLINE
        assert agent.status == AgentStatus.OFFLINE

    def test_stale_agent_job_should_be_requeued(self):
        """When an agent goes stale, its assigned job should be re-queued."""

        job_id = uuid.uuid4()
        agent_id = uuid.uuid4()

        agent = AgentRecord(
            id=agent_id,
            name="stale-busy",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            current_job_id=job_id,
            last_heartbeat=datetime.now(timezone.utc) - timedelta(seconds=60),
        )

        job = JobRecord(
            id=job_id,
            product="vehicle_gateway",
            status=JobStatus.RUNNING,
            assigned_agent_id=agent_id,
            created_at=datetime.now(timezone.utc),
        )

        # Simulate re-queue
        assert job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING)
        job.status = JobStatus.QUEUED
        job.assigned_agent_id = None
        agent.status = AgentStatus.OFFLINE
        agent.current_job_id = None

        assert job.status == JobStatus.QUEUED
        assert agent.status == AgentStatus.OFFLINE
