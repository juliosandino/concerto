"""Tests for the agent CLI entry point."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from concerto_agent.cli import app
from concerto_shared.enums import Product
from typer.testing import CliRunner

runner = CliRunner()


class TestCLI:
    """Tests for the typer CLI."""

    def test_run_creates_agent_and_calls_run(self):
        """Verify the run command loads settings, creates ConcertoAgent, and calls run()."""
        mock_agent = AsyncMock()

        with (
            patch(
                "concerto_agent.cli.load_settings",
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
                "concerto_agent.cli.ConcertoAgent",
                return_value=mock_agent,
            ) as mock_cls,
            patch("concerto_agent.cli.asyncio.run") as mock_asyncio_run,
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 0
        mock_cls.assert_called_once()
        mock_asyncio_run.assert_called_once()

    def test_run_passes_config_path(self):
        """Verify the run command forwards --config to load_settings."""
        mock_agent = AsyncMock()

        with (
            patch(
                "concerto_agent.cli.load_settings",
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
                "concerto_agent.cli.ConcertoAgent",
                return_value=mock_agent,
            ),
            patch("concerto_agent.cli.asyncio.run"),
        ):
            result = runner.invoke(app, ["--config", "/tmp/agent.yaml"])

        assert result.exit_code == 0
        mock_load.assert_called_once_with("/tmp/agent.yaml")

    def test_help(self):
        """Verify --help works."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "agent" in result.output.lower()
