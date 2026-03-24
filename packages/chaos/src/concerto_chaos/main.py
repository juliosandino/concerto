from __future__ import annotations

import argparse
import asyncio

from concerto_chaos.config import CHAOS_PRESETS, ChaosSettings
from concerto_chaos.profiles import create_profile
from concerto_chaos.simulator import run_chaos_agent
from loguru import logger


async def _run(num_agents: int, controller_url: str, chaos_level: str) -> None:
    params = CHAOS_PRESETS.get(chaos_level)
    if not params:
        logger.error(f"Unknown chaos level: {chaos_level} (use low/medium/high)")
        return

    logger.info(
        f"Launching {num_agents} chaos agents at {controller_url} (chaos_level={chaos_level})"
    )

    async with asyncio.TaskGroup() as tg:
        for i in range(num_agents):
            profile = create_profile(params)
            tg.create_task(
                run_chaos_agent(
                    agent_index=i,
                    controller_url=controller_url,
                    profile=profile,
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Concerto Chaos Simulator")
    parser.add_argument(
        "--agents", "-n", type=int, default=5, help="Number of mock agents"
    )
    parser.add_argument(
        "--controller-url",
        default="ws://localhost:8000/ws/agent",
        help="Controller WebSocket URL",
    )
    parser.add_argument(
        "--chaos-level",
        choices=["low", "medium", "high"],
        default="medium",
        help="Chaos intensity level",
    )
    args = parser.parse_args()

    try:
        asyncio.run(_run(args.agents, args.controller_url, args.chaos_level))
    except KeyboardInterrupt:
        logger.info("Chaos simulator stopped")


if __name__ == "__main__":
    main()
