"""Tests for controller configuration."""

from concerto_controller.config import Settings, settings


class TestSettings:
    """Tests for the Settings class."""

    def test_default_values(self):
        """Verify default setting values."""
        s = Settings()
        assert "postgresql+asyncpg" in s.database_url
        assert s.heartbeat_timeout_sec == 15
        assert s.heartbeat_check_interval_sec == 5
        assert s.ws_host == "0.0.0.0"
        assert s.ws_port == 8000

    def test_env_prefix_override(self, monkeypatch):
        """Verify CONCERTO_ env prefix overrides defaults."""
        monkeypatch.setenv("CONCERTO_WS_PORT", "9000")
        monkeypatch.setenv("CONCERTO_HEARTBEAT_TIMEOUT_SEC", "30")
        s = Settings()
        assert s.ws_port == 9000
        assert s.heartbeat_timeout_sec == 30

    def test_module_level_singleton(self):
        """Verify the module-level settings instance exists."""
        assert isinstance(settings, Settings)
