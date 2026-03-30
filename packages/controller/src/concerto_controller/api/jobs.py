"""REST API endpoints for job management."""

from __future__ import annotations

import uuid

from concerto_controller.db.models import JobRecord
from concerto_controller.db.session import get_session
from concerto_shared.enums import JobStatus, Product
from concerto_shared.models import JobInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobCreateBody(BaseModel):
    """Request body for creating a new job."""

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

    return JobInfo.from_record(job)


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
    return [JobInfo.from_record(r) for r in result.scalars().all()]


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> JobInfo:
    """Get a specific job by ID."""
    job = await session.get(JobRecord, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobInfo.from_record(job)
