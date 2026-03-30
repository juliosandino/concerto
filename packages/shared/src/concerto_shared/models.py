"""Shared Pydantic models for API responses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Generic, Self, TypeVar
from uuid import UUID

from concerto_shared.enums import AgentStatus, JobStatus, Product
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from concerto_controller.db.models import AgentRecord, JobRecord


RecordT = TypeVar("RecordT")


class RecordBackedInfo(BaseModel, ABC, Generic[RecordT]):
    """Abstract API model built from an ORM record."""

    @classmethod
    @abstractmethod
    def from_record(cls, record: RecordT) -> Self:
        """Build an API model from an ORM record."""


class AgentInfo(RecordBackedInfo["AgentRecord"]):
    """Public-facing agent information returned by REST endpoints."""

    id: UUID
    name: str
    capabilities: list[Product]
    status: AgentStatus
    current_job_id: UUID | None = None
    last_heartbeat: datetime | None = None

    @classmethod
    def from_record(cls, agent: AgentRecord) -> AgentInfo:
        """Build an API model from an agent ORM record."""
        return cls(
            id=agent.id,
            name=agent.name,
            capabilities=[Product(capability) for capability in agent.capabilities],
            status=agent.status,
            current_job_id=agent.current_job_id,
            last_heartbeat=agent.last_heartbeat,
        )


class JobInfo(RecordBackedInfo["JobRecord"]):
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

    @classmethod
    def from_record(cls, job: JobRecord) -> JobInfo:
        """Build an API model from a job ORM record."""
        return cls(
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
