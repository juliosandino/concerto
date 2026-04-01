"""Tests for the agent CLI entry point."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from concerto_agent.cli import app
from concerto_shared.enums import Product
from typer.testing import CliRunner

runner = CliRunner()


class TestCLI:
    """Tests for the typer CLI."""

    def test_run_with_defaults(self):
        """Verify the run command creates ConcertoAgent with defaults and calls run()."""
        mock_agent = AsyncMock()

        with (
            patch(
                "concerto_agent.cli.ConcertoAgent",
                return_value=mock_agent,
            ) as mock_cls,
            patch("concerto_agent.cli.asyncio.run") as mock_asyncio_run,
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 0
        mock_cls.assert_called_once_with(
            agent_name="testbed-01",
            capabilities=[Product.VEHICLE_GATEWAY, Product.ASSET_GATEWAY],
            controller_url="ws://localhost:8000/ws/agent",
            heartbeat_interval=5,
            reconnect_base_delay=1.0,
            reconnect_max_delay=30.0,
        )
        mock_asyncio_run.assert_called_once()

    def test_run_with_cli_args(self):
        """Verify CLI flags override defaults."""
        mock_agent = AsyncMock()

        with (
            patch(
                "concerto_agent.cli.ConcertoAgent",
                return_value=mock_agent,
            ) as mock_cls,
            patch("concerto_agent.cli.asyncio.run"),
        ):
            result = runner.invoke(
                app,
                [
                    "--agent-name",
                    "my-agent",
                    "--capability",
                    "vehicle_gateway",
                    "--controller-url",
                    "ws://other:9000/ws/agent",
                    "--heartbeat-interval",
                    "10",
                ],
            )

        assert result.exit_code == 0
        mock_cls.assert_called_once_with(
            agent_name="my-agent",
            capabilities=[Product.VEHICLE_GATEWAY],
            controller_url="ws://other:9000/ws/agent",
            heartbeat_interval=10,
            reconnect_base_delay=1.0,
            reconnect_max_delay=30.0,
        )

    def test_run_with_env_vars(self, monkeypatch):
        """Verify environment variables override defaults."""
        monkeypatch.setenv("AGENT_AGENT_NAME", "env-agent")
        monkeypatch.setenv("AGENT_HEARTBEAT_INTERVAL_SEC", "15")
        mock_agent = AsyncMock()

        with (
            patch(
                "concerto_agent.cli.ConcertoAgent",
                return_value=mock_agent,
            ) as mock_cls,
            patch("concerto_agent.cli.asyncio.run"),
        ):
            result = runner.invoke(app, [])

        assert result.exit_code == 0
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["agent_name"] == "env-agent"
        assert call_kwargs["heartbeat_interval"] == 15

    def test_help(self):
        """Verify --help works."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "agent" in result.output.lower()
