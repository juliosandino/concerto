from __future__ import annotations

from pathlib import Path

import yaml
from concerto_shared.enums import Product
from pydantic_settings import BaseSettings


class AgentSettings(BaseSettings):
    agent_name: str = "testbed-01"
    capabilities: list[Product] = [Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY]
    controller_url: str = "ws://localhost:8000/ws/agent"
    heartbeat_interval_sec: int = 5
    reconnect_base_delay_sec: float = 1.0
    reconnect_max_delay_sec: float = 30.0

    model_config = {"env_prefix": "AGENT_"}


def load_settings(config_path: str | Path | None = None) -> AgentSettings:
    """Load agent settings, optionally overriding from a YAML file.

    YAML keys ``agent_name`` and ``capabilities`` are read from the file.
    Environment variables always take highest precedence.
    """
    overrides: dict = {}
    if config_path is not None:
        path = Path(config_path)
        with path.open() as f:
            data = yaml.safe_load(f) or {}
        if "agent_name" in data:
            overrides["agent_name"] = data["agent_name"]
        if "capabilities" in data:
            overrides["capabilities"] = data["capabilities"]
    return AgentSettings(**overrides)
