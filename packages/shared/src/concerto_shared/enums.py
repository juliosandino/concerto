"""Shared enumerations for agent status, job status, and products."""

from enum import StrEnum


class AgentStatus(StrEnum):
    """Possible states of an agent."""

    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"


class JobStatus(StrEnum):
    """Possible states of a job."""

    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    PASSED = "passed"
    FAILED = "failed"


class Product(StrEnum):
    """Product types available for testing."""

    VEHICLE_GATEWAY = "vehicle_gateway"
    ASSET_GATEWAY = "asset_gateway"
    ENVIRONMENTAL_MONITOR = "environmental_monitor"
    INDUSTRIAL_GATEWAY = "industrial_gateway"
