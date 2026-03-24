"""Tests for agent configuration and YAML settings loader."""

from __future__ import annotations

import textwrap

from concerto_agent.config import AgentSettings, load_settings
from concerto_shared.enums import Product


class TestAgentSettings:
    """Tests for the AgentSettings defaults."""

    def test_default_values(self):
        """Verify defaults are applied when no overrides are given."""
        settings = AgentSettings()
        assert settings.agent_name == "testbed-01"
        assert settings.capabilities == [
            Product.VEHICLE_GATEWAY,
            Product.ASSET_GATEWAY,
        ]
        assert settings.controller_url == "ws://localhost:8000/ws/agent"
        assert settings.heartbeat_interval_sec == 5
        assert settings.reconnect_base_delay_sec == 1.0
        assert settings.reconnect_max_delay_sec == 30.0

    def test_env_prefix_override(self, monkeypatch):
        """Verify environment variables with AGENT_ prefix override defaults."""
        monkeypatch.setenv("AGENT_AGENT_NAME", "env-agent")
        monkeypatch.setenv("AGENT_HEARTBEAT_INTERVAL_SEC", "10")
        settings = AgentSettings()
        assert settings.agent_name == "env-agent"
        assert settings.heartbeat_interval_sec == 10


class TestLoadSettings:
    """Tests for the load_settings function."""

    def test_no_config_path_returns_defaults(self):
        """When no config path is given, defaults are used."""
        settings = load_settings(config_path=None)
        assert settings.agent_name == "testbed-01"

    def test_yaml_overrides_agent_name(self, tmp_path):
        """YAML file overrides agent_name."""
        cfg = tmp_path / "agent.yaml"
        cfg.write_text("agent_name: yaml-agent\n")
        settings = load_settings(config_path=cfg)
        assert settings.agent_name == "yaml-agent"

    def test_yaml_overrides_capabilities(self, tmp_path):
        """YAML file overrides capabilities list."""
        cfg = tmp_path / "agent.yaml"
        cfg.write_text(textwrap.dedent("""\
            capabilities:
              - vehicle_gateway
            """))
        settings = load_settings(config_path=cfg)
        assert settings.capabilities == [Product.VEHICLE_GATEWAY]

    def test_yaml_with_both_fields(self, tmp_path):
        """YAML file overrides both agent_name and capabilities."""
        cfg = tmp_path / "agent.yaml"
        cfg.write_text(textwrap.dedent("""\
            agent_name: dual-agent
            capabilities:
              - asset_gateway
            """))
        settings = load_settings(config_path=cfg)
        assert settings.agent_name == "dual-agent"
        assert settings.capabilities == [Product.ASSET_GATEWAY]

    def test_yaml_empty_file(self, tmp_path):
        """An empty YAML file falls back to defaults."""
        cfg = tmp_path / "empty.yaml"
        cfg.write_text("")
        settings = load_settings(config_path=cfg)
        assert settings.agent_name == "testbed-01"

    def test_yaml_without_known_keys(self, tmp_path):
        """Unknown keys in YAML are silently ignored."""
        cfg = tmp_path / "agent.yaml"
        cfg.write_text("unknown_key: value\n")
        settings = load_settings(config_path=cfg)
        assert settings.agent_name == "testbed-01"

    def test_string_config_path(self, tmp_path):
        """String path (not Path object) works correctly."""
        cfg = tmp_path / "agent.yaml"
        cfg.write_text("agent_name: str-path-agent\n")
        settings = load_settings(config_path=str(cfg))
        assert settings.agent_name == "str-path-agent"
