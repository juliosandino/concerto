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
    async def test_sends_running_then_passed(self):
        """Verify executor sends RUNNING then PASSED."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        assignment = JobAssignMessage(
            job_id=job_id, product=Product.VEHICLE_GATEWAY, duration=0.01
        )
        send_fn = AsyncMock()

        await execute_job(
            agent_id=agent_id,
            assignment=assignment,
            send_fn=send_fn,
        )

        assert send_fn.call_count == 2

        # First call: RUNNING
        first_msg = send_fn.call_args_list[0][0][0]
        assert isinstance(first_msg, JobStatusMessage)
        assert first_msg.status == JobStatus.RUNNING
        assert first_msg.job_id == job_id

        # Second call: PASSED
        second_msg = send_fn.call_args_list[1][0][0]
        assert isinstance(second_msg, JobStatusMessage)
        assert second_msg.status == JobStatus.PASSED
        assert second_msg.result is not None

    @pytest.mark.asyncio
    async def test_result_contains_duration(self):
        """Verify result string includes the job duration."""
        agent_id = uuid.uuid4()
        job_id = uuid.uuid4()
        assignment = JobAssignMessage(
            job_id=job_id, product=Product.ASSET_GATEWAY, duration=2.5
        )
        send_fn = AsyncMock()

        await execute_job(
            agent_id=agent_id,
            assignment=assignment,
            send_fn=send_fn,
        )

        second_msg = send_fn.call_args_list[1][0][0]
        assert "2.5s" in second_msg.result
