"""Tests for database session utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from concerto_controller.db.session import (
    _alembic_cfg,
    async_session,
    engine,
    get_session,
    init_db,
)


class TestAlembicCfg:
    """Tests for _alembic_cfg."""

    def test_returns_config_with_url(self):
        """Verify _alembic_cfg returns a Config with the DB URL set."""
        cfg = _alembic_cfg()
        url = cfg.get_main_option("sqlalchemy.url")
        assert "postgresql+asyncpg" in url


class TestModuleLevelObjects:
    """Tests for module-level engine and session factory."""

    def test_engine_exists(self):
        """Verify the async engine is created."""
        assert engine is not None

    def test_async_session_factory_exists(self):
        """Verify the async session factory is created."""
        assert async_session is not None


class TestInitDb:
    """Tests for init_db."""

    @pytest.mark.asyncio
    async def test_init_db_calls_alembic_upgrade(self):
        """Verify init_db runs alembic upgrade head via run_in_executor."""
        with patch("concerto_controller.db.session.command.upgrade") as mock_upgrade:
            await init_db()
            mock_upgrade.assert_called_once()
            args = mock_upgrade.call_args[0]
            assert args[1] == "head"


class TestGetSession:
    """Tests for get_session dependency."""

    @pytest.mark.asyncio
    async def test_yields_session(self):
        """Verify get_session yields an async session."""
        mock_session = AsyncMock()

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "concerto_controller.db.session.async_session",
            return_value=mock_cm,
        ):
            gen = get_session()
            session = await anext(gen)
            assert session is mock_session
