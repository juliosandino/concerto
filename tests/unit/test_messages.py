"""Tests for WebSocket message serialization and parsing."""

from __future__ import annotations

import uuid

import pytest
from concerto_shared.enums import JobStatus, Product
from concerto_shared.messages import (
    DisconnectMessage,
    HeartbeatMessage,
    JobAssignMessage,
    JobStatusMessage,
    MessageType,
    RegisterAckMessage,
    RegisterMessage,
    parse_message,
)


class TestRegisterMessage:
    def test_serialization_roundtrip(self):
        msg = RegisterMessage(
            agent_name="test-agent",
            capabilities=[Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY],
        )
        raw = msg.model_dump_json()
        parsed = parse_message(raw)
        assert isinstance(parsed, RegisterMessage)
        assert parsed.agent_name == "test-agent"
        assert parsed.capabilities == [Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY]
        assert parsed.type == MessageType.REGISTER

    def test_type_field_is_set_automatically(self):
        msg = RegisterMessage(
            agent_name="test",
            capabilities=[],
        )
        assert msg.type == MessageType.REGISTER


class TestRegisterAckMessage:
    def test_serialization_roundtrip(self):
        agent_id = uuid.uuid4()
        msg = RegisterAckMessage(agent_id=agent_id)
        raw = msg.model_dump_json()
        parsed = parse_message(raw)
        assert isinstance(parsed, RegisterAckMessage)
        assert parsed.agent_id == agent_id
        assert parsed.type == MessageType.REGISTER_ACK


class TestDisconnectMessage:
    def test_serialization_roundtrip(self):
        msg = DisconnectMessage(reason="test removal")
        raw = msg.model_dump_json()
        parsed = parse_message(raw)
        assert isinstance(parsed, DisconnectMessage)
        assert parsed.reason == "test removal"
        assert parsed.type == MessageType.DISCONNECT

    def test_default_reason(self):
        msg = DisconnectMessage()
        assert msg.reason == "Removed by controller"


class TestHeartbeatMessage:
    def test_serialization_roundtrip(self):
        agent_id = uuid.uuid4()
        msg = HeartbeatMessage(agent_id=agent_id)
        parsed = parse_message(msg.model_dump_json())
        assert isinstance(parsed, HeartbeatMessage)
        assert parsed.agent_id == agent_id


class TestJobAssignMessage:
    def test_serialization_roundtrip(self):
        job_id = uuid.uuid4()
        msg = JobAssignMessage(job_id=job_id, product=Product.VEHICLE_GATEWAY)
        parsed = parse_message(msg.model_dump_json())
        assert isinstance(parsed, JobAssignMessage)
        assert parsed.job_id == job_id
        assert parsed.product == Product.VEHICLE_GATEWAY


class TestJobStatusMessage:
    def test_completed_roundtrip(self):
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        msg = JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result="Test passed",
        )
        parsed = parse_message(msg.model_dump_json())
        assert isinstance(parsed, JobStatusMessage)
        assert parsed.status == JobStatus.COMPLETED
        assert parsed.result == "Test passed"

    def test_failed_with_no_result(self):
        msg = JobStatusMessage(
            agent_id=uuid.uuid4(),
            job_id=uuid.uuid4(),
            status=JobStatus.FAILED,
        )
        assert msg.result is None


class TestParseMessage:
    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_message("not json")

    def test_unknown_type_raises(self):
        with pytest.raises(Exception):
            parse_message('{"type": "unknown", "data": {}}')

    def test_missing_required_field_raises(self):
        with pytest.raises(Exception):
            parse_message('{"type": "register"}')
