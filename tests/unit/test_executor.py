"""Tests for the agent job executor."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from concerto_agent.executor import execute_job
from concerto_shared.enums import JobStatus, Product
from concerto_shared.messages import JobAssignMessage, JobStatusMessage


class TestExecuteJob:
    """Tests for the execute_job coroutine."""

    @pytest.mark.asyncio
    async def test_sends_running_then_final_status(self):
        """Verify executor sends RUNNING then COMPLETED when failure_rate is 0."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        assignment = JobAssignMessage(job_id=job_id, product=Product.VEHICLE_GATEWAY)
        send_fn = AsyncMock()

        await execute_job(
            agent_id=agent_id,
            assignment=assignment,
            send_fn=send_fn,
            min_duration=0.01,
            max_duration=0.02,
            failure_rate=0.0,  # never fail
        )

        assert send_fn.call_count == 2

        # First call: RUNNING
        first_msg = send_fn.call_args_list[0][0][0]
        assert isinstance(first_msg, JobStatusMessage)
        assert first_msg.status == JobStatus.RUNNING
        assert first_msg.job_id == job_id

        # Second call: COMPLETED (failure_rate=0)
        second_msg = send_fn.call_args_list[1][0][0]
        assert isinstance(second_msg, JobStatusMessage)
        assert second_msg.status == JobStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_failure_rate_1_always_fails(self):
        """Verify executor reports FAILED when failure_rate is 1."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        assignment = JobAssignMessage(job_id=job_id, product=Product.ASSET_GATEWAY)
        send_fn = AsyncMock()

        await execute_job(
            agent_id=agent_id,
            assignment=assignment,
            send_fn=send_fn,
            min_duration=0.01,
            max_duration=0.02,
            failure_rate=1.0,  # always fail
        )

        second_msg = send_fn.call_args_list[1][0][0]
        assert second_msg.status == JobStatus.FAILED
        assert second_msg.result is not None
