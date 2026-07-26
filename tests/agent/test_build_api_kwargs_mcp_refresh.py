"""Test for the build_api_kwargs MCP safety-net refresh (issue #71736).

When MCP tools are registered AFTER the agent's tool snapshot (e.g. background
discovery finishes just before the first API call), build_api_kwargs should
detect the stale generation and pull in the new tools before the API call.
"""
import sys
import types
import unittest
from unittest import mock


class TestBuildApiKwargsMcpRefresh(unittest.TestCase):
    """Verify the safety-net MCP refresh in build_api_kwargs."""

    def _make_agent(self, *, tools=None, tool_snapshot_generation=5, provider="custom"):
        """Create a minimal fake agent for testing."""
        agent = mock.MagicMock()
        agent.tools = tools or []
        agent._tool_snapshot_generation = tool_snapshot_generation
        agent.provider = provider
        agent.api_mode = "chat_completions"
        agent.base_url = "http://localhost:11434/v1"
        agent._base_url_lower = "http://localhost:11434/v1"
        agent.model = "qwen3:14b"
        agent.reasoning_config = None
        agent.request_overrides = None
        agent.max_tokens = 4096
        agent._max_tokens_param = lambda v: {"max_tokens": v}
        agent._resolved_api_call_timeout = lambda: 60.0
        agent._is_qwen_portal = lambda: False
        agent._is_openrouter_url = lambda: False
        agent._transport_cache = {}
        agent._get_transport = mock.MagicMock()
        return agent

    def _fake_transport(self):
        """Create a fake transport that returns a simple dict."""
        transport = mock.MagicMock()
        transport.build_kwargs = mock.MagicMock(return_value={
            "model": "qwen3:14b",
            "messages": [],
            "tools": [],
        })
        return transport

    def test_refresh_when_registry_generation_advanced(self):
        """When registry._generation > agent._tool_snapshot_generation and
        MCP tools exist, refresh_agent_mcp_tools should be called and the
        updated tools passed to build_kwargs."""
        from agent.chat_completion_helpers import build_api_kwargs

        agent = self._make_agent(
            tools=[{"function": {"name": "terminal"}}],
            tool_snapshot_generation=5,
        )
        transport = self._fake_transport()
        agent._get_transport.return_value = transport

        # Simulate: MCP tools registered, generation advanced
        mock_refresh = mock.MagicMock()
        mock_has_mcp = mock.MagicMock(return_value=True)

        # After refresh, agent.tools should have MCP tools
        def _refresh_side_effect(*a, **kw):
            agent.tools = [
                {"function": {"name": "terminal"}},
                {"function": {"name": "mcp__homeassistant__GetDateTime"}},
            ]
            agent.valid_tool_names = {"terminal", "mcp__homeassistant__GetDateTime"}
            agent._tool_snapshot_generation = 7

        mock_refresh.side_effect = _refresh_side_effect

        # Build a fake registry with advanced generation
        mock_registry = mock.MagicMock()
        mock_registry._generation = 7

        # Create a proper fake module object
        fake_mcp_mod = types.ModuleType("tools.mcp_tool")
        fake_mcp_mod.has_registered_mcp_tools = mock_has_mcp
        fake_mcp_mod.refresh_agent_mcp_tools = mock_refresh

        with mock.patch.dict(sys.modules, {"tools.mcp_tool": fake_mcp_mod}):
            with mock.patch("tools.registry.registry", mock_registry):
                build_api_kwargs(agent, api_messages=[])

        # refresh_agent_mcp_tools should have been called
        mock_refresh.assert_called_once()
        mock_refresh.assert_called_with(agent, quiet_mode=True)

        # The tools passed to build_kwargs should include MCP tools
        build_kwargs_call = transport.build_kwargs.call_args
        tools_arg = build_kwargs_call.kwargs.get("tools")
        tool_names = {t["function"]["name"] for t in tools_arg}
        self.assertIn("mcp__homeassistant__GetDateTime", tool_names)

    def test_no_refresh_when_generation_matches(self):
        """When registry._generation == agent._tool_snapshot_generation,
        no refresh should happen."""
        from agent.chat_completion_helpers import build_api_kwargs

        agent = self._make_agent(
            tools=[{"function": {"name": "terminal"}}],
            tool_snapshot_generation=5,
        )
        transport = self._fake_transport()
        agent._get_transport.return_value = transport

        mock_refresh = mock.MagicMock()
        mock_has_mcp = mock.MagicMock(return_value=True)

        mock_registry = mock.MagicMock()
        mock_registry._generation = 5  # same as agent

        with mock.patch.dict(sys.modules, {"tools.mcp_tool": mock.MagicMock()}):
            mcp_mod = sys.modules["tools.mcp_tool"]
            mcp_mod.has_registered_mcp_tools = mock_has_mcp
            mcp_mod.refresh_agent_mcp_tools = mock_refresh

            with mock.patch("tools.registry.registry", mock_registry):
                build_api_kwargs(agent, api_messages=[])

        # No refresh should happen
        mock_refresh.assert_not_called()

    def test_no_refresh_when_no_mcp_tools(self):
        """When no MCP tools are registered, no refresh should happen."""
        from agent.chat_completion_helpers import build_api_kwargs

        agent = self._make_agent(
            tools=[{"function": {"name": "terminal"}}],
            tool_snapshot_generation=5,
        )
        transport = self._fake_transport()
        agent._get_transport.return_value = transport

        mock_refresh = mock.MagicMock()
        mock_has_mcp = mock.MagicMock(return_value=False)  # No MCP tools

        mock_registry = mock.MagicMock()
        mock_registry._generation = 7  # advanced, but no MCP tools

        with mock.patch.dict(sys.modules, {"tools.mcp_tool": mock.MagicMock()}):
            mcp_mod = sys.modules["tools.mcp_tool"]
            mcp_mod.has_registered_mcp_tools = mock_has_mcp
            mcp_mod.refresh_agent_mcp_tools = mock_refresh

            with mock.patch("tools.registry.registry", mock_registry):
                build_api_kwargs(agent, api_messages=[])

        # No refresh should happen (no MCP tools to refresh)
        mock_refresh.assert_not_called()

    def test_no_refresh_when_mcp_tool_module_not_loaded(self):
        """When tools.mcp_tool is not in sys.modules, no refresh should happen."""
        from agent.chat_completion_helpers import build_api_kwargs

        agent = self._make_agent(
            tools=[{"function": {"name": "terminal"}}],
            tool_snapshot_generation=5,
        )
        transport = self._fake_transport()
        agent._get_transport.return_value = transport

        mock_refresh = mock.MagicMock()

        # Remove tools.mcp_tool from sys.modules if present
        had_mcp = "tools.mcp_tool" in sys.modules
        if had_mcp:
            saved = sys.modules.pop("tools.mcp_tool")

        try:
            mock_registry = mock.MagicMock()
            mock_registry._generation = 7

            with mock.patch("tools.registry.registry", mock_registry):
                build_api_kwargs(agent, api_messages=[])
        finally:
            if had_mcp:
                sys.modules["tools.mcp_tool"] = saved

        mock_refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
