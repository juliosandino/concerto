from __future__ import annotations

import argparse
import asyncio

from concerto_agent.client import AgentClient
from concerto_agent.config import load_settings
from concerto_agent.executor import execute_job
from concerto_shared.messages import JobAssignMessage, WSMessage
from loguru import logger

_client: AgentClient | None = None


async def _on_message(msg: WSMessage) -> None:
    """Handle incoming messages from the controller."""
    if isinstance(msg, JobAssignMessage) and _client and _client.agent_id:
        asyncio.create_task(
            execute_job(
                agent_id=_client.agent_id,
                assignment=msg,
                send_fn=_client.send,
            )
        )


async def _run(config_path: str | None = None) -> None:
    global _client
    settings = load_settings(config_path)
    _client = AgentClient(
        agent_name=settings.agent_name,
        capabilities=settings.capabilities,
        controller_url=settings.controller_url,
        heartbeat_interval=settings.heartbeat_interval_sec,
        reconnect_base_delay=settings.reconnect_base_delay_sec,
        reconnect_max_delay=settings.reconnect_max_delay_sec,
        on_message=_on_message,
    )
    logger.info(f"Agent {settings.agent_name} starting (caps={settings.capabilities})")
    await _client.run()


def main() -> None:
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
