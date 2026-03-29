"""Agent CLI entry point and main event loop."""

from __future__ import annotations

import argparse
import asyncio

from concerto_agent.client import AgentClient
from concerto_agent.config import load_settings
from loguru import logger


async def _run(config_path: str | None = None) -> None:

    settings = load_settings(config_path)
    client = AgentClient(
        agent_name=settings.agent_name,
        capabilities=settings.capabilities,
        controller_url=settings.controller_url,
        heartbeat_interval=settings.heartbeat_interval_sec,
        reconnect_base_delay=settings.reconnect_base_delay_sec,
        reconnect_max_delay=settings.reconnect_max_delay_sec,
    )
    logger.info(f"Agent {settings.agent_name} starting (caps={settings.capabilities})")
    await client.run()


def main() -> None:
    """Parse arguments and run the agent."""
    parser = argparse.ArgumentParser(description="Concerto test agent")
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to a YAML config file (agent_name, capabilities)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.config))


if __name__ == "__main__":
    main()
    main()
