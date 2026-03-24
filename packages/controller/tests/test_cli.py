"""Tests for CLI helpers."""

from __future__ import annotations

import sys
from unittest.mock import patch

from concerto_controller.cli import downgrade, migrate, revision


class TestMigrate:
    """Tests for the migrate function."""

    def test_calls_alembic_upgrade_head(self):
        """Verify migrate runs alembic upgrade head."""
        with patch("concerto_controller.cli.command.upgrade") as mock_upgrade:
            migrate()
            mock_upgrade.assert_called_once()
            assert mock_upgrade.call_args[0][1] == "head"


class TestRevision:
    """Tests for the revision function."""

    def test_default_message(self, monkeypatch):
        """Verify revision uses 'new migration' when no -m flag provided."""
        monkeypatch.setattr(sys, "argv", ["concerto-revision"])
        with patch("concerto_controller.cli.command.revision") as mock_rev:
            revision()
            mock_rev.assert_called_once()
            assert mock_rev.call_args[1]["message"] == "new migration"
            assert mock_rev.call_args[1]["autogenerate"] is True

    def test_custom_message(self, monkeypatch):
        """Verify revision uses the -m argument when provided."""
        monkeypatch.setattr(sys, "argv", ["concerto-revision", "-m", "add users"])
        with patch("concerto_controller.cli.command.revision") as mock_rev:
            revision()
            assert mock_rev.call_args[1]["message"] == "add users"

    def test_m_flag_at_end_without_value(self, monkeypatch):
        """Verify revision falls back to default when -m is last arg with no value."""
        monkeypatch.setattr(sys, "argv", ["concerto-revision", "-m"])
        with patch("concerto_controller.cli.command.revision") as mock_rev:
            revision()
            assert mock_rev.call_args[1]["message"] == "new migration"


class TestDowngrade:
    """Tests for the downgrade function."""

    def test_default_target(self, monkeypatch):
        """Verify downgrade defaults to -1 (one step back)."""
        monkeypatch.setattr(sys, "argv", ["concerto-downgrade"])
        with patch("concerto_controller.cli.command.downgrade") as mock_dg:
            downgrade()
            mock_dg.assert_called_once()
            assert mock_dg.call_args[0][1] == "-1"

    def test_custom_target(self, monkeypatch):
        """Verify downgrade uses the provided target."""
        monkeypatch.setattr(sys, "argv", ["concerto-downgrade", "base"])
        with patch("concerto_controller.cli.command.downgrade") as mock_dg:
            downgrade()
            assert mock_dg.call_args[0][1] == "base"
