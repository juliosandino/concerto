"""Shared Pydantic models for API responses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from concerto_shared.enums import AgentStatus, JobStatus, Product
from pydantic import BaseModel, Field


class AgentInfo(BaseModel):
    """Public-facing agent information returned by REST endpoints."""

    id: UUID
    name: str
    capabilities: list[Product]
    status: AgentStatus
    current_job_id: UUID | None = None
    last_heartbeat: datetime | None = None


class JobInfo(BaseModel):
    """Public-facing job information returned by REST endpoints."""

    id: UUID
    product: Product
    status: JobStatus
    assigned_agent_id: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str | None = Field(
        default=None, description="Result summary or error message"
    )
    duration: float | None = None
