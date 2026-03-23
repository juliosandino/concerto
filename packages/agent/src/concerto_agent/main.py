from __future__ import annotations

import asyncio
import logging

from concerto_shared.messages import JobAssignMessage, WSMessage
from concerto_agent.client import AgentClient
from concerto_agent.config import agent_settings
from concerto_agent.executor import execute_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_client: AgentClient | None = None


async def _on_message(msg: WSMessage) -> None:
    """Handle incoming messages from the controller."""
    if isinstance(msg, JobAssignMessage) and _client:
        # Execute job in a background task so we don't block the receive loop
        asyncio.create_task(
            execute_job(
                agent_id=agent_settings.agent_id,
                assignment=msg,
                send_fn=_client.send,
            )
        )


async def _run() -> None:
    global _client
    _client = AgentClient(
        agent_id=agent_settings.agent_id,
        agent_name=agent_settings.agent_name,
        capabilities=agent_settings.capabilities,
        controller_url=agent_settings.controller_url,
        heartbeat_interval=agent_settings.heartbeat_interval_sec,
        reconnect_base_delay=agent_settings.reconnect_base_delay_sec,
        reconnect_max_delay=agent_settings.reconnect_max_delay_sec,
        on_message=_on_message,
    )
    logger.info(
        "Agent %s starting (id=%s, caps=%s)",
        agent_settings.agent_name,
        agent_settings.agent_id,
        agent_settings.capabilities,
    )
    await _client.run()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
