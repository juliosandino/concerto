"""Chaos simulator configuration and preset profiles."""
from pydantic_settings import BaseSettings


class ChaosSettings(BaseSettings):
    """Chaos simulator settings loaded from environment variables."""

    num_agents: int = 5
    controller_url: str = "ws://localhost:8000/ws/agent"
    chaos_level: str = "medium"  # low, medium, high

    # Failure probabilities by chaos level
    # These are overridden based on chaos_level in get_chaos_params()
    dropout_probability: float = 0.0
    min_uptime_sec: float = 10.0
    max_uptime_sec: float = 60.0
    heartbeat_delay_factor: float = 1.0  # multiplier on normal heartbeat interval
    job_failure_rate: float = 0.1
    flap_probability: float = 0.0

    model_config = {"env_prefix": "CHAOS_"}


CHAOS_PRESETS: dict[str, dict] = {
    "low": {
        "dropout_probability": 0.1,
        "min_uptime_sec": 30.0,
        "max_uptime_sec": 120.0,
        "heartbeat_delay_factor": 1.0,
        "job_failure_rate": 0.05,
        "flap_probability": 0.0,
    },
    "medium": {
        "dropout_probability": 0.3,
        "min_uptime_sec": 15.0,
        "max_uptime_sec": 60.0,
        "heartbeat_delay_factor": 1.5,
        "job_failure_rate": 0.15,
        "flap_probability": 0.1,
    },
    "high": {
        "dropout_probability": 0.6,
        "min_uptime_sec": 5.0,
        "max_uptime_sec": 30.0,
        "heartbeat_delay_factor": 3.0,
        "job_failure_rate": 0.3,
        "flap_probability": 0.25,
    },
}
