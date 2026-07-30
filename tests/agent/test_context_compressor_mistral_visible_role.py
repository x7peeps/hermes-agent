"""Tests for Mistral template-visible role alternation fix (#74086).

Mistral chat templates exempt tool-flow messages (role="tool" and
assistant messages with ``tool_calls``) from their role-alternation check.
The original code used the literal last/first role when picking the summary
role, which could be "tool" — invisible to the template. This caused
consecutive "user→user" or "assistant→assistant" visible roles, triggering
a permanent HTTP 500 Jinja Exception on every compaction.

Fix: ``_nearest_visible_role_in_head()`` and ``_nearest_visible_role_in_tail()``
scan past tool-flow messages to find the nearest role the template counts.
"""

import sys
import types
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Stub out optional heavy dependencies not installed in the test environment
sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())

from agent.context_compressor import (
    ContextCompressor,
    COMPRESSED_SUMMARY_METADATA_KEY,
)


def _make_compressor(**overrides):
    """Build a ContextCompressor with enough state to pass compress() guards.

    Keyword arguments override any default attribute, making it easy to
    tweak ``tail_token_budget``, ``protect_last_n``, etc. per test.
    """
    c = ContextCompressor.__new__(ContextCompressor)
    c.quiet_mode = True
    c.model = "test/model"
    c.provider = "test"
    c.base_url = "http://test"
    c.api_key = "test-key"
    c.api_mode = ""
    c.context_length = 128000
    c.threshold_tokens = 64000
    c.threshold_percent = 0.50
    c.tail_token_budget = 20000
    c.protect_first_n = 2
    c.protect_last_n = 2
    c.summary_model = ""
    c.last_prompt_tokens = 100000
    c.last_completion_tokens = 0
    c._summary_failure_cooldown_until = 0.0
    c.abort_on_summary_failure = False
    c._last_compress_aborted = False
    c._summary_model_fallen_back = False
    c.compression_count = 0
    c._context_probed = False
    c._last_compression_savings_pct = 100.0
    c._ineffective_compression_count = 0
    c._last_summary_error = None
    c._last_summary_dropped_count = 0
    c._last_summary_fallback_used = False
    c._last_aux_model_failure_error = None
    c._last_aux_model_failure_model = None
    c.last_real_prompt_tokens = 0
    c.last_compression_rough_tokens = 0
    c.last_rough_tokens_when_real_prompt_fit = 0
    c.awaiting_real_usage_after_compression = False
    c._previous_summary = None
    c._summary_has_user_turn = True
    c._last_summary_auth_failure = False
    c._last_summary_network_failure = False
    for key, val in overrides.items():
        setattr(c, key, val)
    return c


def _tool_call_msg(tool_call_id="call_dummy"):
    """Build an assistant message with tool_calls (invisible to Mistral templates)."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": "dummy_tool", "arguments": "{}"},
            }
        ],
    }


def _tool_result_msg(tool_call_id="call_dummy"):
    """Build a tool-result message (role='tool', invisible to Mistral templates)."""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": "tool output"}


# ---------------------------------------------------------------------------
# Helper: run compress with mocked summary, return the summary message(s)
# ---------------------------------------------------------------------------

def _compress_and_get_summaries(c, messages):
    """Compress *messages* with a mocked ``_generate_summary`` return and
    return the list of summary messages (those bearing the metadata flag)."""
    with patch.object(c, "_generate_summary", return_value="[CONTEXT COMPACTION] Dummy summary."):
        result = c.compress(messages)
    return [m for m in result if m.get(COMPRESSED_SUMMARY_METADATA_KEY)]


# ---------------------------------------------------------------------------
# Head scenarios — the head boundary is determined by _protect_head_size.
# With protect_first_n=2 and a system message, the head is messages[0:3].
# ---------------------------------------------------------------------------

def test_mistral_head_ends_with_assistant_tool_calls():
    """Head ends with ``user → assistant(tool_calls)``.

    The assistant message carries ``tool_calls`` so Mistral does not count it.
    The nearest visible predecessor is ``"user"`` → summary must be ``"assistant"``.

    Without the fix, ``last_head_role = "assistant"`` (literal) would produce
    ``summary_role = "user"``, which can collide with a tail that starts with
    ``"user"`` — HTTP 500 on Mistral.
    """
    c = _make_compressor()

    # head = [system, user, assistant(tool_calls)] — index 2 is in head
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Search for something"},
        _tool_call_msg(tool_call_id="call_1"),
        # middle (compressed)
        {"role": "tool", "tool_call_id": "call_1", "content": "search results here"},
        {"role": "assistant", "content": "I found the results."},
        {"role": "user", "content": "Now refine the search"},
        # tail (protected)
        {"role": "assistant", "content": "Refined."},
        {"role": "user", "content": "Thanks"},
        {"role": "assistant", "content": "Welcome."},
    ]

    summary_msgs = _compress_and_get_summaries(c, messages)
    assert summary_msgs, "Expected a summary message in the compressed result"
    assert summary_msgs[0]["role"] == "assistant", (
        f"When head ends with assistant(tool_calls) the visible predecessor is "
        f"'user', so summary role should be 'assistant'. Got: {summary_msgs[0]['role']!r}"
    )


def test_mistral_head_ends_with_tool_flow_user_tool_assistant():
    """Head ends with ``user → assistant(tool_calls) → tool → user``
    where the head boundary includes the tool message.

    The literal last head role is ``"user"`` (plain — no tool_calls), so
    the summary should be ``"assistant"``. This scenario verifies that the
    helper correctly handles a mixed boundary with tool-flow before it.
    """
    c = _make_compressor(protect_first_n=3)

    # head = [system, user, assistant(tool_calls), tool, user] — last head is plain "user"
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Initial ask"},
        _tool_call_msg(tool_call_id="call_1"),
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        {"role": "user", "content": "Based on that, do X"},
        # middle
        {"role": "assistant", "content": "Doing X."},
        {"role": "user", "content": "Good"},
        # tail
        {"role": "assistant", "content": "Done."},
        {"role": "user", "content": "Bye"},
        {"role": "assistant", "content": "Cheers"},
    ]

    summary_msgs = _compress_and_get_summaries(c, messages)
    assert summary_msgs, "Expected a summary message in the compressed result"
    # last_head_role = "user" → summary_role = "assistant"
    assert summary_msgs[0]["role"] == "assistant", (
        f"Head ends with plain 'user' after tool-flow, summary should be "
        f"'assistant'. Got: {summary_msgs[0]['role']!r}"
    )


def test_mistral_plain_head_last_assistant():
    """Head ends with a plain assistant (no ``tool_calls``) — the most
    common non-Mistral scenario. The fix must not alter existing behavior:
    ``last_head_role = "assistant"`` → ``summary_role = "user"``.
    """
    c = _make_compressor()

    # head = [system, user, assistant]
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        # middle
        {"role": "user", "content": "Search X"},
        {"role": "assistant", "content": "Results for X"},
        {"role": "user", "content": "More"},
        # tail
        {"role": "assistant", "content": "More results"},
        {"role": "user", "content": "Thanks"},
        {"role": "assistant", "content": "Welcome"},
    ]

    summary_msgs = _compress_and_get_summaries(c, messages)
    assert summary_msgs, "Expected a summary message in the compressed result"
    assert summary_msgs[0]["role"] == "user", (
        f"Plain head ending with 'assistant' should produce summary role 'user'. "
        f"Got: {summary_msgs[0]['role']!r}"
    )


# ---------------------------------------------------------------------------
# Tail scenarios — first_tail_role is computed by _nearest_visible_role_in_tail
# ---------------------------------------------------------------------------

def test_mistral_tail_starts_with_tool():
    """Tail starts with a ``tool`` message. The visible first role is the
    next non-tool message. This exercises ``_nearest_visible_role_in_tail``."""
    c = _make_compressor(protect_last_n=3)

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Initial ask"},
        {"role": "assistant", "content": "Initial answer"},
        # middle
        {"role": "user", "content": "Use tool"},
        _tool_call_msg(tool_call_id="call_t1"),
        _tool_result_msg(tool_call_id="call_t1"),
        # tail starts with tool
        {"role": "tool", "tool_call_id": "call_t1", "content": "extra output"},
        {"role": "assistant", "content": "Final answer"},
        {"role": "user", "content": "OK"},
        {"role": "assistant", "content": "Bye"},
    ]

    summary_msgs = _compress_and_get_summaries(c, messages)
    assert summary_msgs, "Expected a summary message in the compressed result"
    # Must be valid (user or assistant), no crash
    assert summary_msgs[0]["role"] in ("user", "assistant"), (
        f"Summary role must be valid, got {summary_msgs[0]['role']!r}"
    )


def test_mistral_tail_starts_with_assistant_tool_calls():
    """Tail starts with an ``assistant`` message carrying ``tool_calls``.
    Mistral ignores it for alternation; the first visible tail role is
    the next non-tool-flow message."""
    c = _make_compressor(protect_last_n=3)

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Initial ask"},
        {"role": "assistant", "content": "Initial answer"},
        # middle
        {"role": "user", "content": "Trigger tool"},
        # tail starts with assistant(tool_calls)
        _tool_call_msg(tool_call_id="call_t1"),
        _tool_result_msg(tool_call_id="call_t1"),
        {"role": "assistant", "content": "Final answer"},
        {"role": "user", "content": "OK"},
        {"role": "assistant", "content": "Bye"},
    ]

    summary_msgs = _compress_and_get_summaries(c, messages)
    assert summary_msgs, "Expected a summary message in the compressed result"
    assert summary_msgs[0]["role"] in ("user", "assistant"), (
        f"Summary role must be valid, got {summary_msgs[0]['role']!r}"
    )


# ---------------------------------------------------------------------------
# Mixed / safety-net scenarios
# ---------------------------------------------------------------------------

def test_mistral_tool_flow_in_middle_not_confused():
    """Tool-flow messages in the compressed middle must not confuse the
    visible-role computation for a head whose literal last message is a
    plain assistant (no tool_calls)."""
    c = _make_compressor()

    # head = [system, user, assistant] — plain assistant, no tool-flow
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "First ask"},
        {"role": "assistant", "content": "First reply"},
        # tool flow in middle, not at head boundary
        {"role": "user", "content": "Use a tool"},
        _tool_call_msg(tool_call_id="call_m1"),
        _tool_result_msg(tool_call_id="call_m1"),
        # tail
        {"role": "assistant", "content": "Final"},
        {"role": "user", "content": "Last ask"},
        {"role": "assistant", "content": "Last answer"},
    ]

    summary_msgs = _compress_and_get_summaries(c, messages)
    assert summary_msgs, "Expected a summary message in the compressed result"

    # head ends with plain "assistant" → last_head_role = "assistant" → summary "user"
    assert summary_msgs[0]["role"] == "user", (
        f"Tool-flow in middle should not affect role computation. "
        f"Expected 'user', got {summary_msgs[0]['role']!r}"
    )


def test_mistral_all_tool_flow_no_user_turn():
    """Edge case: head contains only system + assistant(tool_calls) + tool
    with no plain user turn in the entire transcript. The zero-user-turn
    guard (``_force_user_leading``) should fire, pinning summary to
    ``"user"`` regardless of the visible-role computation.

    This guards against regressions where the Mistral fix accidentally
    bypasses the ``_force_user_leading`` protections for #58753.
    """
    c = _make_compressor(protect_first_n=1)

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Do work"},  # the only user turn
        _tool_call_msg(tool_call_id="call_1"),
        _tool_result_msg(tool_call_id="call_1"),
        {"role": "assistant", "content": "Work done."},
        {"role": "user", "content": "Continue"},
        {"role": "assistant", "content": "Continuing."},
        {"role": "user", "content": "Final"},
        {"role": "assistant", "content": "Done."},
    ]

    # Force the only user turn into the compressed middle so no user
    # survives in either head or tail.
    with patch.object(c, "_find_tail_cut_by_tokens", return_value=7):
        summary_msgs = _compress_and_get_summaries(c, messages)

    assert summary_msgs, "Expected a summary message in the compressed result"
    assert summary_msgs[0]["role"] == "user", (
        f"Zero-user-turn guard must force summary role 'user'. "
        f"Got: {summary_msgs[0]['role']!r}"
    )
