from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class FailureProfile:
    """Combined failure profile for a chaos mock agent."""

    dropout_probability: float = 0.0
    min_uptime_sec: float = 30.0
    max_uptime_sec: float = 120.0
    heartbeat_delay_factor: float = 1.0
    job_failure_rate: float = 0.1
    flap_probability: float = 0.0

    def should_dropout(self) -> bool:
        return random.random() < self.dropout_probability

    def get_uptime(self) -> float:
        return random.uniform(self.min_uptime_sec, self.max_uptime_sec)

    def should_flap(self) -> bool:
        return random.random() < self.flap_probability

    def get_heartbeat_interval(self, base_interval: float) -> float:
        return base_interval * self.heartbeat_delay_factor

    def should_fail_job(self) -> bool:
        return random.random() < self.job_failure_rate


def create_profile(chaos_params: dict) -> FailureProfile:
    """Create a FailureProfile from chaos parameter dict, randomizing slightly."""
    return FailureProfile(
        dropout_probability=chaos_params["dropout_probability"]
        * random.uniform(0.5, 1.5),
        min_uptime_sec=chaos_params["min_uptime_sec"] * random.uniform(0.7, 1.3),
        max_uptime_sec=chaos_params["max_uptime_sec"] * random.uniform(0.7, 1.3),
        heartbeat_delay_factor=chaos_params["heartbeat_delay_factor"]
        * random.uniform(0.8, 1.2),
        job_failure_rate=chaos_params["job_failure_rate"] * random.uniform(0.5, 1.5),
        flap_probability=chaos_params["flap_probability"] * random.uniform(0.5, 1.5),
    )
