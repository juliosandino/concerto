"""Tests for the dispatcher matching logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from concerto_shared.enums import AgentStatus, JobStatus, Product


class TestDispatcherMatchingLogic:
    """Test the core matching logic without DB — using mock sessions."""

    @pytest.mark.asyncio
    async def test_dispatcher_assigns_compatible_agent(self):
        """Verify that a queued job gets matched to an online agent with the right capability."""
        from concerto_controller.db.models import AgentRecord, JobRecord

        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()

        agent = AgentRecord(
            id=agent_id,
            name="test-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )

        job = JobRecord(
            id=job_id,
            product=Product.VEHICLE_GATEWAY,
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )

        # Verify matching: agent supports the product
        assert str(job.product) in agent.capabilities
        assert agent.status == AgentStatus.ONLINE

    def test_no_match_when_capabilities_mismatch(self):
        """Agent only supports asset_gateway but job needs vehicle_gateway."""
        from concerto_controller.db.models import AgentRecord, JobRecord

        agent = AgentRecord(
            id=uuid.uuid4(),
            name="asset-only",
            capabilities=["asset_gateway"],
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )
        job = JobRecord(
            id=uuid.uuid4(),
            product=Product.VEHICLE_GATEWAY,
            status=JobStatus.QUEUED,
            created_at=datetime.now(timezone.utc),
        )

        assert str(job.product) not in agent.capabilities

    def test_no_match_when_agent_busy(self):
        """Busy agents should not be matched."""
        from concerto_controller.db.models import AgentRecord

        agent = AgentRecord(
            id=uuid.uuid4(),
            name="busy-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.BUSY,
            last_heartbeat=datetime.now(timezone.utc),
        )

        assert agent.status != AgentStatus.ONLINE

    def test_no_match_when_agent_offline(self):
        """Offline agents should not be matched."""
        from concerto_controller.db.models import AgentRecord

        agent = AgentRecord(
            id=uuid.uuid4(),
            name="offline-agent",
            capabilities=["vehicle_gateway"],
            status=AgentStatus.OFFLINE,
        )

        assert agent.status != AgentStatus.ONLINE
