from enum import StrEnum


class AgentStatus(StrEnum):
    ONLINE = "online"
    BUSY = "busy"
    OFFLINE = "offline"


class JobStatus(StrEnum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Product(StrEnum):
    VEHICLE_GATEWAY = "vehicle_gateway"
    ASSET_GATEWAY = "asset_gateway"
    ENVIRONMENTAL_MONITOR = "environmental_monitor"
    INDUSTRIAL_GATEWAY = "industrial_gateway"
