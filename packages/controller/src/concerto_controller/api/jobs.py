from __future__ import annotations

import uuid

from concerto_controller.db.models import JobRecord
from concerto_controller.db.session import get_session
from concerto_shared.enums import JobStatus, Product
from concerto_shared.models import JobInfo
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobCreateRequest:
    """Thin wrapper — FastAPI will parse from JSON body."""

    def __init__(self, product: Product):
        self.product = product


from pydantic import BaseModel


class JobCreateBody(BaseModel):
    product: Product
    duration: float | None = None


@router.post("", status_code=201)
async def create_job(
    body: JobCreateBody,
    session: AsyncSession = Depends(get_session),
) -> JobInfo:
    """Submit a new test job to the queue."""
    job = JobRecord(
        id=uuid.uuid4(),
        product=body.product,
        status=JobStatus.QUEUED,
        duration=body.duration,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Trigger dispatcher asynchronously
    from concerto_controller.scheduler.dispatcher import try_dispatch

    await try_dispatch(session)

    return _to_info(job)


@router.get("")
async def list_jobs(
    status: JobStatus | None = None,
    product: Product | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[JobInfo]:
    """List all jobs, optionally filtered by status or product."""
    stmt = select(JobRecord).order_by(JobRecord.created_at.desc())
    if status:
        stmt = stmt.where(JobRecord.status == status)
    if product:
        stmt = stmt.where(JobRecord.product == product)
    result = await session.execute(stmt)
    return [_to_info(r) for r in result.scalars().all()]


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JobInfo:
    """Get a specific job by ID."""
    job = await session.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_info(job)


def _to_info(job: JobRecord) -> JobInfo:
    return JobInfo(
        id=job.id,
        product=job.product,
        status=job.status,
        assigned_agent_id=job.assigned_agent_id,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=job.result,
        duration=job.duration,
    )
