"""Chaos simulator CLI entry point."""
from __future__ import annotations

import argparse
import asyncio
from urllib.parse import urlparse

from concerto_chaos.config import CHAOS_PRESETS
from concerto_chaos.profiles import create_profile
from concerto_chaos.simulator import run_chaos_agent
from loguru import logger


async def _run_chaos(num_agents: int, controller_url: str, chaos_level: str) -> None:
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


def _derive_http_url(ws_url: str) -> str:
    """Convert ws://host:port/ws/agent → http://host:port"""
    parsed = urlparse(ws_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    return f"{scheme}://{parsed.netloc}"


async def _run_scenarios(controller_url: str, runtime: float) -> None:
    from concerto_chaos.scenarios import print_report, run_scenarios

    http_base = _derive_http_url(controller_url)
    logger.info(
        f"Running chaos scenarios against {controller_url} (http={http_base}, runtime={runtime:.0f}s)"
    )
    results = await run_scenarios(controller_url, http_base, runtime)
    print_report(results)


def main() -> None:
    """Parse CLI arguments and run the selected mode."""
    parser = argparse.ArgumentParser(description="Concerto Chaos Simulator")
    parser.add_argument(
        "--mode",
        choices=["chaos", "scenarios"],
        default="chaos",
        help="Run mode: 'chaos' for random failure agents, 'scenarios' for structured verification tests",
    )
    parser.add_argument(
        "--agents", "-n", type=int, default=5, help="Number of mock agents (chaos mode)"
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
        help="Chaos intensity level (chaos mode)",
    )
    parser.add_argument(
        "--runtime",
        type=float,
        default=300.0,
        help="Max runtime in seconds (scenarios mode)",
    )
    args = parser.parse_args()

    try:
        if args.mode == "scenarios":
            asyncio.run(_run_scenarios(args.controller_url, args.runtime))
        else:
            asyncio.run(_run_chaos(args.agents, args.controller_url, args.chaos_level))
    except KeyboardInterrupt:
        logger.info("Chaos simulator stopped")


if __name__ == "__main__":
    main()
