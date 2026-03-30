"""Tests for shared API models."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from concerto_shared.enums import AgentStatus, JobStatus, Product
from concerto_shared.models import AgentInfo, JobInfo, RecordBackedInfo


class TestRecordBackedInfo:
    """Tests for the abstract record-backed info contract."""

    def test_requires_from_record_implementation(self):
        """Subclasses must implement from_record before they can be instantiated."""

        class BrokenInfo(RecordBackedInfo[object]):
            pass

        with pytest.raises(TypeError):
            BrokenInfo()


class TestAgentInfo:
    """Tests for AgentInfo helpers."""

    def test_from_record(self):
        """Build an AgentInfo from an ORM-like record."""

        class AgentRecordStub:
            id = uuid4()
            name = "alpha"
            capabilities = ["vehicle_gateway", "asset_gateway"]
            status = AgentStatus.ONLINE
            current_job_id = None
            last_heartbeat = datetime.now(timezone.utc)

        info = AgentInfo.from_record(AgentRecordStub())

        assert info.id == AgentRecordStub.id
        assert info.name == "alpha"
        assert info.capabilities == [Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY]
        assert info.status == AgentStatus.ONLINE


class TestJobInfo:
    """Tests for JobInfo helpers."""

    def test_from_record(self):
        """Build a JobInfo from an ORM-like record."""

        class JobRecordStub:
            id = uuid4()
            product = Product.VEHICLE_GATEWAY
            status = JobStatus.QUEUED
            assigned_agent_id = None
            created_at = datetime.now(timezone.utc)
            started_at = None
            completed_at = None
            result = None
            duration = 5.0

        info = JobInfo.from_record(JobRecordStub())

        assert info.id == JobRecordStub.id
        assert info.product == Product.VEHICLE_GATEWAY
        assert info.status == JobStatus.QUEUED
        assert info.duration == 5.0
