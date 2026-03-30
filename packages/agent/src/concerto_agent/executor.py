"""Job execution logic for the agent."""

from __future__ import annotations

import asyncio
import uuid

from concerto_shared.enums import JobStatus
from concerto_shared.messages import JobAssignMessage, JobStatusMessage
from loguru import logger


async def execute_job(
    agent_id: uuid.UUID,
    assignment: JobAssignMessage,
    send_fn,
) -> None:
    """Simulate executing a test job.

    Sends RUNNING status, sleeps for a random duration, then sends COMPLETED or FAILED based on failure_rate
    probability.
    """
    job_id = assignment.job_id
    logger.info(f"Starting job {job_id} (product={assignment.product})")

    # Report running
    await send_fn(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.RUNNING,
        )
    )

    # Simulate work — use job-specified duration if provided
    await asyncio.sleep(assignment.duration)

    # Determine outcome
    status = JobStatus.PASSED
    result = f"Test completed after {assignment.duration:.1f}s"
    logger.info(f"Job {job_id} completed after {assignment.duration:.1f}s")

    await send_fn(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=status,
            result=result,
        )
    )
