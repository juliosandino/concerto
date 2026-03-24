"""Controllable mock agent for structured chaos scenario testing."""
from __future__ import annotations

import asyncio
import uuid

import websockets
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


class ManagedAgent:
    """A controllable mock agent for structured chaos scenario testing."""

    def __init__(self, name: str, capabilities: list[Product], ws_url: str) -> None:
        self.name = name
        self.capabilities = capabilities
        self._ws_url = ws_url
        self._ws: websockets.ClientConnection | None = None
        self.agent_id: uuid.UUID | None = None
        self.current_job: JobAssignMessage | None = None
        self._job_queue: asyncio.Queue[JobAssignMessage] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._job_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Connect to the controller, register, and start background loops."""
        self._ws = await websockets.connect(self._ws_url)
        reg = RegisterMessage(agent_name=self.name, capabilities=self.capabilities)
        await self._ws.send(reg.model_dump_json())
        raw = await self._ws.recv()
        ack = parse_message(raw)
        if not isinstance(ack, RegisterAckMessage):
            raise RuntimeError(f"Expected RegisterAck, got {type(ack).__name__}")
        self.agent_id = ack.agent_id
        logger.debug(f"[{self.name}] Registered (id={self.agent_id})")
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._tasks.append(asyncio.create_task(self._receive_loop()))

    async def stop(self) -> None:
        """Cancel background tasks and close the WebSocket connection."""
        for t in self._tasks:
            t.cancel()
        if self._job_task:
            self._job_task.cancel()
        all_tasks = self._tasks + ([self._job_task] if self._job_task else [])
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        self._tasks.clear()
        self._job_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def wait_for_job(self, timeout: float = 30.0) -> JobAssignMessage:
        """Block until the agent receives a job assignment."""
        return await asyncio.wait_for(self._job_queue.get(), timeout)

    async def fail_current_job(self) -> None:
        """Report the current job as FAILED and cancel its handler."""
        if not self.current_job or not self._ws:
            return
        job_id = self.current_job.job_id
        if self._job_task:
            self._job_task.cancel()
            try:
                await self._job_task
            except (asyncio.CancelledError, Exception):
                pass
            self._job_task = None
        try:
            await self._ws.send(
                JobStatusMessage(
                    agent_id=self.agent_id,
                    job_id=job_id,
                    status=JobStatus.FAILED,
                    result="Chaos: forced early failure",
                ).model_dump_json()
            )
        except Exception:
            pass
        self.current_job = None

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        try:
            while True:
                if self._ws and self.agent_id:
                    await self._ws.send(
                        HeartbeatMessage(agent_id=self.agent_id).model_dump_json()
                    )
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = parse_message(raw)
                if isinstance(msg, DisconnectMessage):
                    logger.debug(f"[{self.name}] Disconnect: {msg.reason}")
                    return
                if isinstance(msg, JobAssignMessage):
                    self.current_job = msg
                    self._job_queue.put_nowait(msg)
                    self._job_task = asyncio.create_task(self._run_job(msg))
        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _run_job(self, job: JobAssignMessage) -> None:
        """Handle a job: report RUNNING, simulate work, report COMPLETED."""
        try:
            await self._ws.send(
                JobStatusMessage(
                    agent_id=self.agent_id,
                    job_id=job.job_id,
                    status=JobStatus.RUNNING,
                ).model_dump_json()
            )
            duration = job.duration or 7.0
            await asyncio.sleep(duration)
            if self.current_job and self.current_job.job_id == job.job_id and self._ws:
                await self._ws.send(
                    JobStatusMessage(
                        agent_id=self.agent_id,
                        job_id=job.job_id,
                        status=JobStatus.COMPLETED,
                        result=f"Completed after {duration:.1f}s",
                    ).model_dump_json()
                )
                self.current_job = None
        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed:
            pass
