"""Tests for the agent CLI entry point and main event loop."""

# pylint: disable=protected-access

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from concerto_agent.main import _on_message, _run, main
from concerto_shared.enums import Product
from concerto_shared.messages import HeartbeatMessage, JobAssignMessage


class TestOnMessage:
    """Tests for the _on_message handler."""

    @pytest.mark.asyncio
    async def test_dispatches_job_assignment(self):
        """Verify _on_message spawns execute_job for JobAssignMessage."""
        import concerto_agent.main as mod

        agent_id = uuid.uuid4()
        mock_client = AsyncMock()
        mock_client.agent_id = agent_id
        mock_client.send = AsyncMock()

        original = mod._client
        mod._client = mock_client
        try:
            msg = JobAssignMessage(job_id=uuid.uuid4(), product=Product.VEHICLE_GATEWAY)
            with patch("concerto_agent.main.asyncio.create_task") as mock_task:
                await _on_message(msg)
                mock_task.assert_called_once()
        finally:
            mod._client = original

    @pytest.mark.asyncio
    async def test_ignores_non_job_messages(self):
        """Verify _on_message ignores messages that are not JobAssignMessage."""
        import concerto_agent.main as mod

        mock_client = AsyncMock()
        mock_client.agent_id = uuid.uuid4()
        original = mod._client
        mod._client = mock_client
        try:
            msg = HeartbeatMessage(agent_id=uuid.uuid4())
            with patch("concerto_agent.main.asyncio.create_task") as mock_task:
                await _on_message(msg)
                mock_task.assert_not_called()
        finally:
            mod._client = original

    @pytest.mark.asyncio
    async def test_ignores_when_no_client(self):
        """Verify _on_message is a no-op when _client is None."""
        import concerto_agent.main as mod

        original = mod._client
        mod._client = None
        try:
            msg = JobAssignMessage(job_id=uuid.uuid4(), product=Product.VEHICLE_GATEWAY)
            with patch("concerto_agent.main.asyncio.create_task") as mock_task:
                await _on_message(msg)
                mock_task.assert_not_called()
        finally:
            mod._client = original

    @pytest.mark.asyncio
    async def test_ignores_when_no_agent_id(self):
        """Verify _on_message is a no-op when client has no agent_id."""
        import concerto_agent.main as mod

        mock_client = AsyncMock()
        mock_client.agent_id = None
        original = mod._client
        mod._client = mock_client
        try:
            msg = JobAssignMessage(job_id=uuid.uuid4(), product=Product.VEHICLE_GATEWAY)
            with patch("concerto_agent.main.asyncio.create_task") as mock_task:
                await _on_message(msg)
                mock_task.assert_not_called()
        finally:
            mod._client = original


class TestRun:
    """Tests for the _run coroutine."""

    @pytest.mark.asyncio
    async def test_run_creates_client_and_calls_run(self):
        """Verify _run loads settings, creates AgentClient, and calls run()."""
        mock_client_instance = AsyncMock()

        with (
            patch(
                "concerto_agent.main.load_settings",
                return_value=AsyncMock(
                    agent_name="test",
                    capabilities=[Product.VEHICLE_GATEWAY],
                    controller_url="ws://localhost:8000/ws/agent",
                    heartbeat_interval_sec=5,
                    reconnect_base_delay_sec=1.0,
                    reconnect_max_delay_sec=30.0,
                ),
            ),
            patch(
                "concerto_agent.main.AgentClient",
                return_value=mock_client_instance,
            ) as mock_cls,
        ):
            await _run(config_path=None)

        mock_cls.assert_called_once()
        mock_client_instance.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_passes_config_path(self):
        """Verify _run forwards the config_path to load_settings."""
        mock_client_instance = AsyncMock()

        with (
            patch(
                "concerto_agent.main.load_settings",
                return_value=AsyncMock(
                    agent_name="yaml-agent",
                    capabilities=[],
                    controller_url="ws://x",
                    heartbeat_interval_sec=5,
                    reconnect_base_delay_sec=1.0,
                    reconnect_max_delay_sec=30.0,
                ),
            ) as mock_load,
            patch(
                "concerto_agent.main.AgentClient",
                return_value=mock_client_instance,
            ),
        ):
            await _run(config_path="/tmp/agent.yaml")

        mock_load.assert_called_once_with("/tmp/agent.yaml")


class TestMain:
    """Tests for the main() CLI entry point."""

    def test_main_parses_args_and_runs(self):
        """Verify main() parses --config and invokes asyncio.run(_run(...))."""
        with (
            patch(
                "concerto_agent.main.argparse.ArgumentParser.parse_args",
                return_value=type("Args", (), {"config": "/tmp/cfg.yaml"})(),
            ),
            patch("concerto_agent.main.asyncio.run") as mock_run,
        ):
            main()
            mock_run.assert_called_once()

    def test_main_default_no_config(self):
        """Verify main() works with no --config arg."""
        with (
            patch(
                "concerto_agent.main.argparse.ArgumentParser.parse_args",
                return_value=type("Args", (), {"config": None})(),
            ),
            patch("concerto_agent.main.asyncio.run") as mock_run,
        ):
            main()
            mock_run.assert_called_once()
