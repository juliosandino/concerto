"""Tests for the concerto-mcp CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from concerto_mcp.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_cli_default_url() -> None:
    with patch("concerto_mcp.cli.ConcertoMCP") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        result = runner.invoke(app)
        assert result.exit_code == 0
        mock_cls.assert_called_once_with("http://localhost:8000")
        mock_instance.run.assert_called_once()


def test_cli_custom_url() -> None:
    with patch("concerto_mcp.cli.ConcertoMCP") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        result = runner.invoke(app, ["--controller-url", "http://custom:9000"])
        assert result.exit_code == 0
        mock_cls.assert_called_once_with("http://custom:9000")
        mock_instance.run.assert_called_once()
