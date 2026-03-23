from __future__ import annotations

import uuid

from pydantic_settings import BaseSettings

from concerto_shared.enums import Product


class AgentSettings(BaseSettings):
    agent_id: uuid.UUID = uuid.uuid4()
    agent_name: str = "testbed-01"
    capabilities: list[Product] = [Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY]
    controller_url: str = "ws://localhost:8000/ws/agent"
    heartbeat_interval_sec: int = 5
    reconnect_base_delay_sec: float = 1.0
    reconnect_max_delay_sec: float = 30.0

    model_config = {"env_prefix": "AGENT_"}


agent_settings = AgentSettings()
