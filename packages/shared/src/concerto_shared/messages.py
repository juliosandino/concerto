"""WebSocket message models and parsers for agent and dashboard protocols."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal, Union
from uuid import UUID

from concerto_shared.enums import JobStatus, Product
from concerto_shared.models import AgentInfo, JobInfo
from pydantic import BaseModel, Field


class MessageType(StrEnum):
    """Discriminator enum for WebSocket message types."""

    REGISTER = "register"
    REGISTER_ACK = "register_ack"
    HEARTBEAT = "heartbeat"
    JOB_ASSIGN = "job_assign"
    JOB_STATUS = "job_status"
    DISCONNECT = "disconnect"
    # Dashboard protocol
    DASHBOARD_SNAPSHOT = "dashboard_snapshot"
    DASHBOARD_REMOVE_AGENT = "dashboard_remove_agent"
    DASHBOARD_CREATE_JOB = "dashboard_create_job"


class RegisterMessage(BaseModel):
    """Agent → Controller: declare identity and capabilities."""

    type: Literal[MessageType.REGISTER] = MessageType.REGISTER
    agent_name: str
    capabilities: list[Product]


class RegisterAckMessage(BaseModel):
    """Controller → Agent: confirm registration with server-assigned ID."""

    type: Literal[MessageType.REGISTER_ACK] = MessageType.REGISTER_ACK
    agent_id: UUID


class HeartbeatMessage(BaseModel):
    """Agent → Controller: periodic liveness signal."""

    type: Literal[MessageType.HEARTBEAT] = MessageType.HEARTBEAT
    agent_id: UUID


class JobAssignMessage(BaseModel):
    """Controller → Agent: assign a test job."""

    type: Literal[MessageType.JOB_ASSIGN] = MessageType.JOB_ASSIGN
    job_id: UUID
    product: Product
    duration: float | None = None


class JobStatusMessage(BaseModel):
    """Agent → Controller: report job execution status."""

    type: Literal[MessageType.JOB_STATUS] = MessageType.JOB_STATUS
    agent_id: UUID
    job_id: UUID
    status: JobStatus
    result: str | None = None


class DisconnectMessage(BaseModel):
    """Controller → Agent: instruct agent to terminate."""

    type: Literal[MessageType.DISCONNECT] = MessageType.DISCONNECT
    reason: str = "Removed by controller"


# ---------------------------------------------------------------------------
# Dashboard protocol
# ---------------------------------------------------------------------------


class DashboardSnapshotMessage(BaseModel):
    """Controller → Dashboard: full state snapshot."""

    type: Literal[MessageType.DASHBOARD_SNAPSHOT] = MessageType.DASHBOARD_SNAPSHOT
    agents: list[AgentInfo]
    jobs: list[JobInfo]


class DashboardRemoveAgentMessage(BaseModel):
    """Dashboard → Controller: remove an agent."""

    type: Literal[MessageType.DASHBOARD_REMOVE_AGENT] = (
        MessageType.DASHBOARD_REMOVE_AGENT
    )
    agent_id: UUID


class DashboardCreateJobMessage(BaseModel):
    """Dashboard → Controller: submit a new job."""

    type: Literal[MessageType.DASHBOARD_CREATE_JOB] = MessageType.DASHBOARD_CREATE_JOB
    product: Product
    duration: float | None = None


# Discriminated union for parsing incoming WebSocket messages
WSMessage = Annotated[
    Union[
        RegisterMessage,
        RegisterAckMessage,
        HeartbeatMessage,
        JobAssignMessage,
        JobStatusMessage,
        DisconnectMessage,
    ],
    Field(discriminator="type"),
]


def parse_message(raw: str | bytes) -> WSMessage:
    """Parse a raw WebSocket text frame into a typed message."""
    data = json.loads(raw)
    from pydantic import TypeAdapter

    adapter = TypeAdapter(WSMessage)
    return adapter.validate_python(data)


# Discriminated union for dashboard WebSocket messages
DashboardWSMessage = Annotated[
    Union[
        DashboardSnapshotMessage,
        DashboardRemoveAgentMessage,
        DashboardCreateJobMessage,
    ],
    Field(discriminator="type"),
]


def parse_dashboard_message(raw: str | bytes) -> DashboardWSMessage:
    """Parse a raw WebSocket text frame into a dashboard message."""
    data = json.loads(raw)
    from pydantic import TypeAdapter

    adapter = TypeAdapter(DashboardWSMessage)
    return adapter.validate_python(data)
