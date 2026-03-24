"""Job execution logic for the agent."""
from __future__ import annotations

import asyncio
import random
import uuid

from concerto_shared.enums import JobStatus
from concerto_shared.messages import JobAssignMessage, JobStatusMessage
from loguru import logger


async def execute_job(
    agent_id: uuid.UUID,
    assignment: JobAssignMessage,
    send_fn,
    min_duration: float = 2.0,
    max_duration: float = 8.0,
    failure_rate: float = 0.1,
) -> None:
    """Simulate executing a test job.

    Sends RUNNING status, sleeps for a random duration, then sends
    COMPLETED or FAILED based on failure_rate probability.
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
    duration = assignment.duration or random.uniform(min_duration, max_duration)
    await asyncio.sleep(duration)

    # Determine outcome
    if random.random() < failure_rate:
        status = JobStatus.FAILED
        result = f"Simulated failure after {duration:.1f}s"
        logger.warning(f"Job {job_id} failed after {duration:.1f}s")
    else:
        status = JobStatus.COMPLETED
        result = f"Test passed after {duration:.1f}s"
        logger.info(f"Job {job_id} completed after {duration:.1f}s")

    await send_fn(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=status,
            result=result,
        )
    )
