"""Chaos mock agent simulator with random failure profiles."""

from __future__ import annotations

import asyncio
import random
import uuid

import websockets
from concerto_chaos.profiles import FailureProfile
from concerto_shared.enums import JobStatus, Product
from concerto_shared.messages import (
    DisconnectMessage,
    HeartbeatMessage,
    JobAssignMessage,
    JobStatusMessage,
    RegisterAckMessage,
    RegisterMessage,
    parse_message,
)
from loguru import logger

AGENT_NAMES = [
    "alpha",
    "bravo",
    "charlie",
    "delta",
    "echo",
    "foxtrot",
    "golf",
    "hotel",
    "india",
    "juliet",
    "kilo",
    "lima",
    "mike",
    "november",
    "oscar",
    "papa",
    "quebec",
    "romeo",
    "sierra",
    "tango",
    "uniform",
    "victor",
    "whiskey",
    "xray",
    "yankee",
    "zulu",
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
                    agent_name=agent_name,
                    capabilities=capabilities,
                )
                await ws.send(reg.model_dump_json())

                # Wait for server-assigned ID
                raw = await ws.recv()
                ack = parse_message(raw)
                if not isinstance(ack, RegisterAckMessage):
                    logger.error(
                        f"[{agent_name}] Expected RegisterAck, got {type(ack).__name__}"
                    )
                    continue
                agent_id = ack.agent_id
                logger.info(
                    f"[{agent_name}] Connected and registered (caps={capabilities})"
                )

                # Determine how long this session will last before dropout
                uptime = (
                    profile.get_uptime() if profile.should_dropout() else float("inf")
                )
                hb_interval = profile.get_heartbeat_interval(base_heartbeat_interval)

                asyncio.get_event_loop().time()

                async def heartbeat_loop():
                    while True:
                        hb = HeartbeatMessage(agent_id=agent_id)
                        await ws.send(hb.model_dump_json())
                        await asyncio.sleep(hb_interval)

                async def receive_loop():
                    async for raw in ws:
                        msg = parse_message(raw)
                        if isinstance(msg, DisconnectMessage):
                            logger.info(
                                f"[{agent_name}] Received disconnect: {msg.reason}"
                            )
                            raise _ChaosDisconnected()
                        if isinstance(msg, JobAssignMessage):
                            await _handle_job(ws, agent_id, agent_name, msg, profile)

                async def dropout_timer():
                    if uptime == float("inf"):
                        # Never dropout — just wait forever
                        await asyncio.Event().wait()
                    else:
                        await asyncio.sleep(uptime)
                        logger.warning(
                            f"[{agent_name}] Chaos dropout after {uptime:.1f}s!"
                        )
                        raise _ChaosDropout()

                _disconnected = False
                try:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(heartbeat_loop())
                        tg.create_task(receive_loop())
                        tg.create_task(dropout_timer())
                except* _ChaosDisconnected:
                    logger.info(f"[{agent_name}] Terminated by controller")
                    _disconnected = True
                except* _ChaosDropout:
                    pass  # Expected — will reconnect

                if _disconnected:
                    return

        except (
            ConnectionError,
            OSError,
            websockets.exceptions.WebSocketException,
        ) as e:
            logger.warning(f"[{agent_name}] Connection error: {e}")

        # Check if this agent should flap (rapid reconnect) or wait
        if profile.should_flap():
            delay = random.uniform(0.5, 2.0)
            logger.info(f"[{agent_name}] Flapping — reconnecting in {delay:.1f}s")
        else:
            delay = random.uniform(3.0, 10.0)
            logger.info(f"[{agent_name}] Reconnecting in {delay:.1f}s")

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
    logger.info(f"[{agent_name}] Received job {job_id} (product={assignment.product})")

    # Report running
    await ws.send(
        JobStatusMessage(
            agent_id=agent_id,
            job_id=job_id,
            status=JobStatus.RUNNING,
        ).model_dump_json()
    )

    # Simulate work — use job-specified duration if provided
    duration = assignment.duration or random.uniform(2.0, 8.0)
    await asyncio.sleep(duration)

    # Chaos: maybe fail
    if profile.should_fail_job():
        status = JobStatus.FAILED
        result = f"Chaos-induced failure after {duration:.1f}s"
        logger.warning(
            f"[{agent_name}] Job {job_id} FAILED (chaos) after {duration:.1f}s"
        )
    else:
        status = JobStatus.COMPLETED
        result = f"Test passed after {duration:.1f}s"
        logger.info(f"[{agent_name}] Job {job_id} COMPLETED after {duration:.1f}s")

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


class _ChaosDisconnected(Exception):
    """Sentinel exception when controller sends a disconnect."""
