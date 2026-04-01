"""Tests for the unified Concerto controller CLI."""

from __future__ import annotations

from unittest.mock import patch

from concerto_controller.cli import app
from typer.testing import CliRunner

runner = CliRunner()


class TestMigrate:
    """Tests for the db migrate command."""

    def test_calls_alembic_upgrade_head(self):
        """Verify migrate runs alembic upgrade head."""
        with patch("concerto_controller.cli.command.upgrade") as mock_upgrade:
            result = runner.invoke(app, ["db", "migrate"])
            assert result.exit_code == 0
            mock_upgrade.assert_called_once()
            assert mock_upgrade.call_args[0][1] == "head"


class TestRevision:
    """Tests for the db revision command."""

    def test_default_message(self):
        """Verify revision uses 'new migration' when no -m flag provided."""
        with patch("concerto_controller.cli.command.revision") as mock_rev:
            result = runner.invoke(app, ["db", "revision"])
            assert result.exit_code == 0
            mock_rev.assert_called_once()
            assert mock_rev.call_args[1]["message"] == "new migration"
            assert mock_rev.call_args[1]["autogenerate"] is True

    def test_custom_message(self):
        """Verify revision uses the -m argument when provided."""
        with patch("concerto_controller.cli.command.revision") as mock_rev:
            result = runner.invoke(app, ["db", "revision", "-m", "add users"])
            assert result.exit_code == 0
            assert mock_rev.call_args[1]["message"] == "add users"


class TestDowngrade:
    """Tests for the db downgrade command."""

    def test_default_target(self):
        """Verify downgrade defaults to -1 (one step back)."""
        with patch("concerto_controller.cli.command.downgrade") as mock_dg:
            result = runner.invoke(app, ["db", "downgrade"])
            assert result.exit_code == 0
            mock_dg.assert_called_once()
            assert mock_dg.call_args[0][1] == "-1"

    def test_custom_target(self):
        """Verify downgrade uses the provided target."""
        with patch("concerto_controller.cli.command.downgrade") as mock_dg:
            result = runner.invoke(app, ["db", "downgrade", "base"])
            assert result.exit_code == 0
            assert mock_dg.call_args[0][1] == "base"


class TestRun:
    """Tests for the run command."""

    def test_calls_uvicorn(self):
        """Verify run starts uvicorn with correct settings."""
        with patch("concerto_controller.cli.uvicorn.run") as mock_run:
            result = runner.invoke(app, ["run"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
