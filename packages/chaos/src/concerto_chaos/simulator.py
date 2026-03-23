from __future__ import annotations

import asyncio
import logging
import random
import uuid

from concerto_shared.enums import JobStatus, Product
from concerto_shared.messages import (
    HeartbeatMessage,
    JobAssignMessage,
    JobStatusMessage,
    RegisterMessage,
    WSMessage,
    parse_message,
)
from concerto_chaos.profiles import FailureProfile

import websockets

logger = logging.getLogger(__name__)

AGENT_NAMES = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
    "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
    "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
    "xray", "yankee", "zulu",
]

ALL_PRODUCTS = list(Product)


def _random_capabilities() -> list[Product]:
    """Pick 1-3 random products as capabilities."""
    k = random.randint(1, min(3, len(ALL_PRODUCTS)))
    return random.sample(ALL_PRODUCTS, k)


async def run_chaos_agent(
    agent_index: int,
    controller_url: str,
    profile: FailureProfile,
    base_heartbeat_interval: float = 5.0,
) -> None:
    """Run a single mock agent with a chaos failure profile.

    The agent connects, registers, sends heartbeats, handles jobs,
    and may randomly disconnect or fail based on its profile.
    """
    agent_id = uuid.uuid4()
    suffix = f"-{agent_index:03d}"
    name_base = AGENT_NAMES[agent_index % len(AGENT_NAMES)]
    agent_name = f"chaos-{name_base}{suffix}"
    capabilities = _random_capabilities()

    while True:
        try:
            async with websockets.connect(controller_url) as ws:
                # Register
                reg = RegisterMessage(
                    agent_id=agent_id,
                    agent_name=agent_name,
                    capabilities=capabilities,
                )
                await ws.send(reg.model_dump_json())
                logger.info("[%s] Connected and registered (caps=%s)", agent_name, capabilities)

                # Determine how long this session will last before dropout
                uptime = profile.get_uptime() if profile.should_dropout() else float("inf")
                hb_interval = profile.get_heartbeat_interval(base_heartbeat_interval)

                session_start = asyncio.get_event_loop().time()

                async def heartbeat_loop():
                    while True:
                        hb = HeartbeatMessage(agent_id=agent_id)
                        await ws.send(hb.model_dump_json())
                        await asyncio.sleep(hb_interval)

                async def receive_loop():
                    async for raw in ws:
                        msg = parse_message(raw)
                        if isinstance(msg, JobAssignMessage):
                            await _handle_job(ws, agent_id, agent_name, msg, profile)

                async def dropout_timer():
                    if uptime == float("inf"):
                        # Never dropout — just wait forever
                        await asyncio.Event().wait()
                    else:
                        await asyncio.sleep(uptime)
                        logger.warning("[%s] Chaos dropout after %.1fs!", agent_name, uptime)
                        raise _ChaosDropout()

                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(heartbeat_loop())
                        tg.create_task(receive_loop())
                        tg.create_task(dropout_timer())
                except* _ChaosDropout:
                    pass  # Expected — will reconnect

        except (ConnectionError, OSError, websockets.exceptions.WebSocketException) as e:
            logger.warning("[%s] Connection error: %s", agent_name, e)

        # Check if this agent should flap (rapid reconnect) or wait
        if profile.should_flap():
            delay = random.uniform(0.5, 2.0)
            logger.info("[%s] Flapping — reconnecting in %.1fs", agent_name, delay)
        else:
            delay = random.uniform(3.0, 10.0)
            logger.info("[%s] Reconnecting in %.1fs", agent_name, delay)

        await asyncio.sleep(delay)


async def _handle_job(
    ws,
    agent_id: uuid.UUID,
    agent_name: str,
    assignment: JobAssignMessage,
    profile: FailureProfile,
) -> None:
    """Execute a job with potential chaos-induced failure."""
    job_id = assignment.job_id
    logger.info("[%s] Received job %s (product=%s)", agent_name, job_id, assignment.product)

    # Report running
    await ws.send(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.RUNNING,
        ).model_dump_json()
    )

    # Simulate work
    duration = random.uniform(2.0, 8.0)
    await asyncio.sleep(duration)

    # Chaos: maybe fail
    if profile.should_fail_job():
        status = JobStatus.FAILED
        result = f"Chaos-induced failure after {duration:.1f}s"
        logger.warning("[%s] Job %s FAILED (chaos) after %.1fs", agent_name, job_id, duration)
    else:
        status = JobStatus.COMPLETED
        result = f"Test passed after {duration:.1f}s"
        logger.info("[%s] Job %s COMPLETED after %.1fs", agent_name, job_id, duration)

    await ws.send(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=status,
            result=result,
        ).model_dump_json()
    )


class _ChaosDropout(Exception):
    """Sentinel exception to trigger a chaos dropout."""
    pass
