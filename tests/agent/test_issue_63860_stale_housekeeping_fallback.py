"""Regression test for issue #63860.

A cached _last_content_with_tools response from a housekeeping-only turn
survives a later substantive tool-only turn. If the model then returns an
empty response, Hermes incorrectly finalizes the older housekeeping narration
instead of invoking the post-tool empty-response nudge.

See: https://github.com/NousResearch/hermes-agent/issues/63860
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/Users/pwndazhang/projects/hermes-agent")

from run_agent import AIAgent


def _tool_defs(*names):
    """Return tool definitions matching what get_tool_definitions produces."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "test tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


def _tool_call(name, call_id):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments="{}"),
    )


def _response(*, content="", finish_reason="stop", tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model="test/model", usage=None)


def test_substantive_tool_only_turn_invalidates_older_housekeeping_fallback():
    """Issue #63860: substantive tool-only turn must clear stale housekeeping fallback.

    Sequence:
    1. Content "I'll begin the work." + todo (housekeeping) → sets _last_content_with_tools
    2. Empty content + web_search (substantive) → should CLEAR stale fallback
    3. Empty content, no tools → should trigger post-tool nudge (not fallback)
    4. Content "Recovered after nudge." → should be the final response
    """
    with (
        patch("run_agent.get_tool_definitions", return_value=_tool_defs("todo", "web_search")),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )

    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.tool_delay = 0
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent.valid_tool_names = {"todo", "web_search"}
    agent.client = MagicMock()
    agent.client.chat.completions.create.side_effect = [
        _response(
            content="I'll begin the work.",
            finish_reason="tool_calls",
            tool_calls=[_tool_call("todo", "todo1")],
        ),
        _response(
            content="",
            finish_reason="tool_calls",
            tool_calls=[_tool_call("web_search", "search1")],
        ),
        _response(content="", finish_reason="stop"),
        _response(content="Recovered after nudge.", finish_reason="stop"),
    ]

    with (
        patch("run_agent.handle_function_call", return_value="ok"),
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("do the full task")

    assert result["final_response"] == "Recovered after nudge."
    assert result["api_calls"] == 4
    assert result["turn_exit_reason"].startswith("text_response")
