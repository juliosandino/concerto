from __future__ import annotations

import asyncio
import logging
import random
import uuid

from concerto_shared.enums import JobStatus
from concerto_shared.messages import JobAssignMessage, JobStatusMessage

logger = logging.getLogger(__name__)


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
    logger.info("Starting job %s (product=%s)", job_id, assignment.product)

    # Report running
    await send_fn(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.RUNNING,
        )
    )

    # Simulate work
    duration = random.uniform(min_duration, max_duration)
    await asyncio.sleep(duration)

    # Determine outcome
    if random.random() < failure_rate:
        status = JobStatus.FAILED
        result = f"Simulated failure after {duration:.1f}s"
        logger.warning("Job %s failed after %.1fs", job_id, duration)
    else:
        status = JobStatus.COMPLETED
        result = f"Test passed after {duration:.1f}s"
        logger.info("Job %s completed after %.1fs", job_id, duration)

    await send_fn(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=status,
            result=result,
        )
    )
