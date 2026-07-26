"""Regression tests for issue #68559: multiplexed gateway terminal backend routing.

These tests prove that when a routed profile turn executes under
``_profile_runtime_scope``, the terminal tool reads the routed profile's
``terminal:`` configuration rather than the gateway-starting profile's
process-global ``TERMINAL_*`` environment variables.
"""
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestTerminalConfigScope:
    """Context-local terminal config scope works in isolation."""

    def test_scope_overrides_env_vars(self, monkeypatch):
        """When a terminal config scope is active, _get_env_config reads from it."""
        from tools.terminal_tool import (
            _get_env_config,
            set_terminal_config_scope,
            reset_terminal_config_scope,
        )

        # Set process-global env vars to a known \"wrong\" value
        monkeypatch.setenv("TERMINAL_ENV", "local")
        monkeypatch.delenv("TERMINAL_DOCKER_IMAGE", raising=False)

        # Activate a scoped config that says \"docker\"
        scoped = {
            "backend": "docker",
            "docker_image": "alpine:latest",
        }
        token = set_terminal_config_scope(scoped)
        try:
            cfg = _get_env_config()
            assert cfg["env_type"] == "docker", (
                f"Expected 'docker' from scope, got {cfg['env_type']}"
            )
            assert cfg["docker_image"] == "alpine:latest", (
                f"Expected 'alpine:latest' from scope, got {cfg['docker_image']}"
            )
        finally:
            reset_terminal_config_scope(token)

    def test_no_scope_falls_back_to_env_vars(self, monkeypatch):
        """Without an active scope, the legacy env-var path is used."""
        from tools.terminal_tool import _get_env_config

        monkeypatch.setenv("TERMINAL_ENV", "ssh")
        monkeypatch.setenv("TERMINAL_SSH_HOST", "example.com")

        cfg = _get_env_config()
        assert cfg["env_type"] == "ssh"
        assert cfg["ssh_host"] == "example.com"

    def test_scope_isolation_concurrent(self):
        """Simulating two profile scopes don't interfere (single-threaded proof)."""
        from tools.terminal_tool import (
            _get_env_config,
            set_terminal_config_scope,
            reset_terminal_config_scope,
        )

        # Profile A: docker
        token_a = set_terminal_config_scope({
            "backend": "docker",
            "docker_image": "python:3.11",
        })
        cfg_a = _get_env_config()
        assert cfg_a["env_type"] == "docker"

        # Profile B: ssh (nested scope)
        token_b = set_terminal_config_scope({
            "backend": "ssh",
            "ssh_host": "remote.example.com",
        })
        cfg_b = _get_env_config()
        assert cfg_b["env_type"] == "ssh"
        assert cfg_b["ssh_host"] == "remote.example.com"

        # After B's scope ends, A's scope is still active
        reset_terminal_config_scope(token_b)
        cfg_a_again = _get_env_config()
        assert cfg_a_again["env_type"] == "docker"

        reset_terminal_config_scope(token_a)


class TestProfileRuntimeScopeTerminalConfig:
    """_profile_runtime_scope installs terminal config for routed profiles."""

    @pytest.fixture
    def tmp_hermes_home(self, tmp_path, monkeypatch):
        """Create a temporary HERMES_HOME with a config.yaml containing terminal settings."""
        home = tmp_path / "hermes"
        home.mkdir()
        config = home / "config.yaml"
        config.write_text(
            "terminal:\n"
            "  backend: docker\n"
            "  docker_image: nikolaik/python-nodejs:python3.11-nodejs20\n"
            "  container_cpu: 2.0\n"
        )
        # Ensure no process-global TERMINAL_* env vars pollute the test
        monkeypatch.delenv("HERMES_HOME", raising=False)
        monkeypatch.delenv("TERMINAL_ENV", raising=False)
        monkeypatch.delenv("TERMINAL_DOCKER_IMAGE", raising=False)
        monkeypatch.setenv("HERMES_HOME", str(home))
        return home

    def test_profile_runtime_scope_applies_terminal_config(self, tmp_hermes_home):
        """_profile_runtime_scope installs the profile's terminal config."""
        from gateway.run import _profile_runtime_scope
        from tools.terminal_tool import _get_env_config, _get_terminal_config_scope

        profile_home = Path(tmp_hermes_home)

        # Before entering scope: no terminal config scope active
        assert _get_terminal_config_scope() is None

        with _profile_runtime_scope(profile_home):
            # Inside scope: terminal config should come from the profile's config.yaml
            scoped = _get_terminal_config_scope()
            assert scoped is not None, "Terminal config scope should be active"
            assert scoped.get("backend") == "docker"
            assert scoped.get("docker_image") == "nikolaik/python-nodejs:python3.11-nodejs20"

            # _get_env_config should read from the scoped config
            cfg = _get_env_config()
            assert cfg["env_type"] == "docker", (
                f"Expected 'docker' from profile config, got {cfg['env_type']}"
            )

        # After exiting scope: terminal config scope is cleared
        assert _get_terminal_config_scope() is None

    def test_profile_runtime_scope_no_terminal_section(self, tmp_path, monkeypatch):
        """Profile without terminal section doesn't break _profile_runtime_scope."""
        home = tmp_path / "hermes"
        home.mkdir()
        config = home / "config.yaml"
        config.write_text("agent:\n  max_turns: 10\n")
        monkeypatch.setenv("HERMES_HOME", str(home))

        from gateway.run import _profile_runtime_scope
        from tools.terminal_tool import _get_terminal_config_scope

        with _profile_runtime_scope(Path(home)):
            # No terminal section → no scope installed → None
            assert _get_terminal_config_scope() is None
