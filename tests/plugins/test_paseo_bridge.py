"""Tests for the paseo-bridge plugin.

Tests cover:
- PaseoDaemonConfig parsing and URL generation
- PaseoBridge message formatting
- Plugin tool registration shape
- Error handling when daemon is unreachable
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestPaseoDaemonConfig:
    """PaseoDaemonConfig parsing and URL generation."""

    def test_defaults(self):
        from plugins.paseo import PaseoDaemonConfig
        cfg = PaseoDaemonConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 6767
        assert cfg.password is None
        assert cfg.use_tls is False

    def test_ws_url_plain(self):
        from plugins.paseo import PaseoDaemonConfig
        cfg = PaseoDaemonConfig(host="localhost", port=8080)
        assert cfg.ws_url == "ws://localhost:8080/ws"

    def test_ws_url_tls(self):
        from plugins.paseo import PaseoDaemonConfig
        cfg = PaseoDaemonConfig(host="localhost", port=8080, use_tls=True)
        assert cfg.ws_url == "wss://localhost:8080/ws"

    def test_from_env_defaults(self, monkeypatch):
        from plugins.paseo import PaseoDaemonConfig
        monkeypatch.delenv("PASEO_LISTEN", raising=False)
        monkeypatch.delenv("PASEO_PASSWORD", raising=False)
        monkeypatch.delenv("PASEO_TLS", raising=False)
        cfg = PaseoDaemonConfig.from_env()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 6767

    def test_from_env_custom_listen(self, monkeypatch):
        from plugins.paseo import PaseoDaemonConfig
        monkeypatch.setenv("PASEO_LISTEN", "10.0.0.1:9090")
        monkeypatch.delenv("PASEO_PASSWORD", raising=False)
        monkeypatch.delenv("PASEO_TLS", raising=False)
        cfg = PaseoDaemonConfig.from_env()
        assert cfg.host == "10.0.0.1"
        assert cfg.port == 9090

    def test_from_env_with_password(self, monkeypatch):
        from plugins.paseo import PaseoDaemonConfig
        monkeypatch.delenv("PASEO_LISTEN", raising=False)
        monkeypatch.setenv("PASEO_PASSWORD", "s3cret")
        monkeypatch.delenv("PASEO_TLS", raising=False)
        cfg = PaseoDaemonConfig.from_env()
        assert cfg.password == "s3cret"

    def test_from_env_tls(self, monkeypatch):
        from plugins.paseo import PaseoDaemonConfig
        monkeypatch.delenv("PASEO_LISTEN", raising=False)
        monkeypatch.delenv("PASEO_PASSWORD", raising=False)
        monkeypatch.setenv("PASEO_TLS", "true")
        cfg = PaseoDaemonConfig.from_env()
        assert cfg.use_tls is True


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------

class TestPaseoAgent:
    """PaseoAgent descriptor."""

    def test_basic(self):
        from plugins.paseo import PaseoAgent
        agent = PaseoAgent(
            agent_id="abc123",
            title="Fix bug #42",
            provider="claude/sonnet",
            workspace_id="ws-1",
            status="running",
        )
        assert agent.agent_id == "abc123"
        assert agent.error is None


# ---------------------------------------------------------------------------
# Bridge tests (mocked WebSocket)
# ---------------------------------------------------------------------------

class TestPaseoBridge:
    """PaseoBridge with mocked WebSocket."""

    def _make_bridge(self):
        from plugins.paseo import PaseoBridge, PaseoDaemonConfig
        cfg = PaseoDaemonConfig(host="127.0.0.1", port=6767)
        return PaseoBridge(config=cfg)

    def _mock_ws(self, bridge, responses):
        """Mock the WebSocket connection with canned responses."""
        mock_ws = AsyncMock()
        bridge._ws = mock_ws
        bridge._message_id = 0

        async def fake_recv():
            return json.dumps(responses.pop(0))

        mock_ws.recv = fake_recv
        mock_ws.send = AsyncMock()
        return mock_ws

    @pytest.mark.asyncio
    async def test_list_providers(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": [
                {
                    "id": "claude",
                    "label": "Claude",
                    "description": "Anthropic's assistant",
                    "available": True,
                    "modes": [{"id": "auto", "label": "Auto mode"}],
                },
            ],
        }
        self._mock_ws(bridge, [canned])

        providers = await bridge.list_providers()
        assert len(providers) == 1
        assert providers[0]["id"] == "claude"
        assert providers[0]["modes"][0]["id"] == "auto"

    @pytest.mark.asyncio
    async def test_list_models(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": [
                {"id": "sonnet", "label": "Claude Sonnet"},
                {"id": "opus", "label": "Claude Opus"},
            ],
        }
        self._mock_ws(bridge, [canned])

        models = await bridge.list_models("claude")
        assert len(models) == 2
        assert models[0]["id"] == "sonnet"

    @pytest.mark.asyncio
    async def test_create_agent(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "agentId": "agent-xyz",
                "workspaceId": "ws-1",
                "title": "Fix bug",
                "provider": "claude/sonnet",
            },
        }
        self._mock_ws(bridge, [canned])

        result = await bridge.create_agent(
            title="Fix bug",
            provider="claude/sonnet",
            initial_prompt="Fix the login bug",
        )
        assert result["agent_id"] == "agent-xyz"
        assert result["workspace_id"] == "ws-1"

    @pytest.mark.asyncio
    async def test_create_agent_with_workspace(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "agentId": "agent-xyz",
                "workspaceId": "ws-2",
                "title": "Feature",
                "provider": "codex/gpt-5.4",
            },
        }
        self._mock_ws(bridge, [canned])

        result = await bridge.create_agent(
            title="Feature",
            provider="codex/gpt-5.4",
            initial_prompt="Add feature X",
            workspace_id="ws-2",
            mode_id="full-access",
            labels=["feature"],
        )
        assert result["agent_id"] == "agent-xyz"

    @pytest.mark.asyncio
    async def test_send_prompt(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"success": True, "message": "Prompt sent"},
        }
        self._mock_ws(bridge, [canned])

        result = await bridge.send_prompt("agent-xyz", "Follow up")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_agents(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": [
                {
                    "agentId": "a1",
                    "title": "Bug fix",
                    "provider": "claude/sonnet",
                    "status": "running",
                    "workspaceId": "ws-1",
                },
            ],
        }
        self._mock_ws(bridge, [canned])

        agents = await bridge.list_agents(since_hours=48)
        assert len(agents) == 1
        assert agents[0]["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_workspaces(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": [
                {"workspaceId": "ws-1", "path": "/tmp/ws-1", "isolation": "local"},
            ],
        }
        self._mock_ws(bridge, [canned])

        workspaces = await bridge.list_workspaces()
        assert len(workspaces) == 1
        assert workspaces[0]["isolation"] == "local"

    @pytest.mark.asyncio
    async def test_create_workspace_local(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "workspaceId": "ws-new",
                "path": "/tmp/ws-new",
                "isolation": "local",
            },
        }
        self._mock_ws(bridge, [canned])

        result = await bridge.create_workspace(isolation="local")
        assert result["workspace_id"] == "ws-new"

    @pytest.mark.asyncio
    async def test_create_workspace_worktree(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "workspaceId": "ws-wt",
                "path": "~/.paseo/worktrees/fix-x",
                "isolation": "worktree",
            },
        }
        self._mock_ws(bridge, [canned])

        result = await bridge.create_workspace(
            isolation="worktree",
            worktree_mode="branch-off",
            branch_name="fix-x",
            base_branch="main",
        )
        assert result["isolation"] == "worktree"

    @pytest.mark.asyncio
    async def test_connection_error(self):
        """ConnectionError raised when daemon is unreachable."""
        from plugins.paseo import PaseoBridge, PaseoDaemonConfig
        cfg = PaseoDaemonConfig(host="127.0.0.1", port=59999)
        bridge = PaseoBridge(config=cfg)

        with pytest.raises((ConnectionError, OSError)):
            await bridge.list_providers()

    @pytest.mark.asyncio
    async def test_daemon_error_response(self):
        bridge = self._make_bridge()
        canned = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"message": "Provider not found"},
        }
        self._mock_ws(bridge, [canned])

        with pytest.raises(RuntimeError, match="Provider not found"):
            await bridge.list_providers()


# ---------------------------------------------------------------------------
# Integration smoke test (daemon not required)
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    """Verify the plugin module can be imported and register function exists."""

    def test_register_function_exists(self):
        from plugins.paseo import register
        assert callable(register)

    def test_bridge_instantiation(self):
        from plugins.paseo import PaseoBridge
        bridge = PaseoBridge()
        assert bridge.config.host == "127.0.0.1"
        assert bridge.config.port == 6767
