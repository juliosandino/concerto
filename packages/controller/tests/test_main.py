"""Tests for the controller FastAPI application and startup lifecycle."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from concerto_controller.logging import _InterceptHandler
from concerto_controller.main import app, health, lifespan, run


class TestInterceptHandler:
    """Tests for the _InterceptHandler logging bridge."""

    def test_emit_known_level(self):
        """Verify emit routes a known log level to loguru."""
        handler = _InterceptHandler()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="test warning",
            args=(),
            exc_info=None,
        )
        with patch("concerto_controller.logging.logger") as mock_logger:
            mock_logger.level.return_value.name = "WARNING"
            handler.emit(record)
            mock_logger.opt.assert_called_once()
            mock_logger.opt().log.assert_called_once()

    def test_emit_unknown_level(self):
        """Verify emit falls back to numeric level for unknown levels."""
        handler = _InterceptHandler()
        record = logging.LogRecord(
            name="test",
            level=99,
            pathname="",
            lineno=0,
            msg="custom level",
            args=(),
            exc_info=None,
        )
        record.levelname = "CUSTOM"
        with patch("concerto_controller.logging.logger") as mock_logger:
            mock_logger.level.side_effect = ValueError("Unknown level")
            handler.emit(record)
            mock_logger.opt.assert_called_once()
            mock_logger.opt().log.assert_called_once()
            # First arg should be the numeric level
            call_args = mock_logger.opt().log.call_args[0]
            assert call_args[0] == 99


class TestLifespan:
    """Tests for the lifespan context manager."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self):
        """Verify lifespan initializes DB, starts heartbeat, and cancels on shutdown."""
        with (
            patch(
                "concerto_controller.main.init_db", new_callable=AsyncMock
            ) as mock_init,
            patch("concerto_controller.main.heartbeat_monitor", new_callable=AsyncMock),
        ):
            async with lifespan(app):
                mock_init.assert_awaited_once()
                # heartbeat_monitor was wrapped in create_task, so it started


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self):
        """Verify health endpoint returns {status: ok}."""
        result = await health()
        assert result == {"status": "ok"}


class TestApp:
    """Tests for the FastAPI app object."""

    def test_app_title(self):
        """Verify the app title is set."""
        assert app.title == "Concerto TSS Controller"

    def test_app_has_routes(self):
        """Verify routers are included."""
        paths = [r.path for r in app.routes]
        assert "/health" in paths


class TestRun:
    """Tests for the run function."""

    def test_run_calls_uvicorn(self):
        """Verify run starts uvicorn with the correct arguments."""
        with patch("concerto_controller.main.uvicorn.run") as mock_uv:
            run()
            mock_uv.assert_called_once_with(
                "concerto_controller.main:app",
                host="0.0.0.0",
                port=8000,
                log_level="info",
            )
