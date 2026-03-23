from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field

from concerto_shared.enums import JobStatus, Product


class MessageType(StrEnum):
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    JOB_ASSIGN = "job_assign"
    JOB_STATUS = "job_status"


class RegisterMessage(BaseModel):
    """Agent → Controller: declare identity and capabilities."""

    type: Literal[MessageType.REGISTER] = MessageType.REGISTER
    agent_id: UUID
    agent_name: str
    capabilities: list[Product]


class HeartbeatMessage(BaseModel):
    """Agent → Controller: periodic liveness signal."""

    type: Literal[MessageType.HEARTBEAT] = MessageType.HEARTBEAT
    agent_id: UUID


class JobAssignMessage(BaseModel):
    """Controller → Agent: assign a test job."""

    type: Literal[MessageType.JOB_ASSIGN] = MessageType.JOB_ASSIGN
    job_id: UUID
    product: Product


class JobStatusMessage(BaseModel):
    """Agent → Controller: report job execution status."""

    type: Literal[MessageType.JOB_STATUS] = MessageType.JOB_STATUS
    agent_id: UUID
    job_id: UUID
    status: JobStatus
    result: str | None = None


# Discriminated union for parsing incoming WebSocket messages
WSMessage = Annotated[
    Union[RegisterMessage, HeartbeatMessage, JobAssignMessage, JobStatusMessage],
    Field(discriminator="type"),
]


def parse_message(raw: str | bytes) -> WSMessage:
    """Parse a raw WebSocket text frame into a typed message."""
    data = json.loads(raw)
    from pydantic import TypeAdapter

    adapter = TypeAdapter(WSMessage)
    return adapter.validate_python(data)
