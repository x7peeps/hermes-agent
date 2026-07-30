from types import SimpleNamespace
from typing import Any

from agent.turn_finalizer import finalize_turn


class FakeAgent:
    def __init__(self):
        self.max_iterations = 90
        self.iteration_budget = SimpleNamespace(remaining=10, used=1, max_total=90)
        self.quiet_mode = True
        self.model = "test-model"
        self.provider = "test-provider"
        self.base_url = ""
        self.session_id = "sess-test"
        self.context_compressor = SimpleNamespace(last_prompt_tokens=0)
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_cache_read_tokens = 0
        self.session_cache_write_tokens = 0
        self.session_reasoning_tokens = 0
        self.session_prompt_tokens = 0
        self.session_completion_tokens = 0
        self.session_total_tokens = 0
        self.session_estimated_cost_usd = 0
        self.session_cost_status = "unknown"
        self.session_cost_source = "test"
        self._tool_guardrail_halt_decision = None
        self._interrupt_message = None
        self._response_was_previewed = True
        self._skill_nudge_interval = 0
        self._iters_since_skill = 0
        self.valid_tool_names = []
        self.persisted_messages: list[dict[str, Any]] | None = None
        self._persist_user_message_idx: int | None = None
        self._persist_user_message_override: Any = None
        self._persist_user_message_timestamp: float | None = None

    def _handle_max_iterations(self, messages, api_call_count):
        raise AssertionError("not expected")

    def _emit_status(self, *_args, **_kwargs):
        pass

    def _safe_print(self, *_args, **_kwargs):
        pass

    def _save_trajectory(self, *_args, **_kwargs):
        pass

    def _cleanup_task_resources(self, *_args, **_kwargs):
        pass

    def _drop_trailing_empty_response_scaffolding(self, messages):
        pass

    def _persist_session(self, messages, conversation_history):
        # Capture the durable write before finalization restores API-local
        # guidance to the returned/live transcript.
        self.persisted_messages = [dict(message) for message in messages]

    def _apply_persist_user_message_override(self, messages):
        idx = self._persist_user_message_idx
        override = self._persist_user_message_override
        if idx is not None and override is not None:
            messages[idx]["content"] = override

    def _file_mutation_verifier_enabled(self):
        return False

    def _turn_completion_explainer_enabled(self):
        return False

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self):
        pass

    def _sync_external_memory_for_turn(self, **_kwargs):
        pass


def test_finalizer_restores_clean_api_local_text_before_return(monkeypatch):
    """One-shot CLI notes do not replay through same-process history."""
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    agent = FakeAgent()
    messages = [
        {"role": "user", "content": "[MODEL SWITCH NOTE]\n\nclean prompt"},
        {"role": "assistant", "content": "Done."},
    ]
    agent._persist_user_message_idx = 0
    agent._persist_user_message_override = "clean prompt"
    agent._persist_user_message_timestamp = None

    result = finalize_turn(
        agent,
        final_response="Done.",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message="[MODEL SWITCH NOTE]\n\nclean prompt",
        original_user_message="clean prompt",
        _should_review_memory=False,
        _turn_exit_reason="text_response(finish_reason=stop)",
    )

    assert agent.persisted_messages is not None
    assert agent.persisted_messages[0]["content"] == "clean prompt"
    assert result["messages"][0]["content"] == "clean prompt"


def test_finalizer_restores_clean_api_local_multimodal_before_return(monkeypatch):
    """A queued note does not remain in the next-turn native image payload."""
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    agent = FakeAgent()
    clean_content = [
        {"type": "text", "text": "Describe the image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    api_content = [
        {"type": "text", "text": "[MODEL SWITCH NOTE]\n\nDescribe the image"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    messages = [
        {"role": "user", "content": api_content},
        {"role": "assistant", "content": "Done."},
    ]
    agent._persist_user_message_idx = 0
    agent._persist_user_message_override = clean_content
    agent._persist_user_message_timestamp = None

    result = finalize_turn(
        agent,
        final_response="Done.",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message=api_content,
        original_user_message=clean_content,
        _should_review_memory=False,
        _turn_exit_reason="text_response(finish_reason=stop)",
    )

    assert agent.persisted_messages is not None
    assert agent.persisted_messages[0]["content"] == clean_content
    assert result["messages"][0]["content"] == clean_content


def test_final_response_closes_tool_tail_before_persistence(monkeypatch):
    """A recovered/previewed final response must be durable in session history.

    Regression for turns where the caller receives a non-empty final_response,
    but the message transcript still ends at a tool result. If persisted that
    way, the next turn reloads a stale/malformed history and can appear to loop
    because the assistant's visible final answer is missing from durable state.
    """
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    agent = FakeAgent()
    messages = [
        {"role": "user", "content": "do it"},
        {
            "role": "assistant",
            "content": "I'll check.",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "terminal", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "name": "terminal", "content": "ok"},
    ]

    result = finalize_turn(
        agent,
        final_response="Done.",
        api_call_count=2,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message="do it",
        original_user_message="do it",
        _should_review_memory=False,
        _turn_exit_reason="fallback_prior_turn_content",
    )

    assert result["messages"][-1] == {"role": "assistant", "content": "Done."}
    assert agent.persisted_messages is not None
    assert agent.persisted_messages[-1] == {"role": "assistant", "content": "Done."}


def test_final_response_fills_pure_tool_call_tail(monkeypatch):
    """A tail assistant row that is a *pure tool-call turn* carries no answer.

    The role check alone ("tail is assistant ⇒ nothing to do") leaves the
    #43849/#44100 invariant unmet when the tail is ``assistant(tool_calls)``
    with no text of its own: the caller and the gateway already delivered
    ``final_response``, but it never reaches the transcript. The next turn then
    replays the user backlog and the model re-answers it — the exact symptom
    that block exists to prevent.
    """
    agent = FakeAgent()
    messages = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "f", "arguments": "{}"}}
            ],
        },
    ]

    result = finalize_turn(
        agent,
        final_response="Here is your answer.",
        api_call_count=3,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="t",
        turn_id="tid",
        user_message="q",
        original_user_message="q",
        _should_review_memory=False,
        _turn_exit_reason="text_response(final)",
    )

    persisted = agent.persisted_messages
    assert any(
        m.get("role") == "assistant" and m.get("content") == result["final_response"]
        for m in persisted
    ), "delivered final_response never reached the durable transcript"
    # Filled in place — no assistant→assistant pair, tool_calls preserved.
    assert persisted[-1]["content"] == "Here is your answer."
    assert persisted[-1]["tool_calls"]
    assert sum(1 for m in persisted if m.get("role") == "assistant") == 1


def test_final_response_does_not_clobber_tool_call_tail_with_text(monkeypatch):
    """A tail tool-call turn that already carries model text must be left alone."""
    agent = FakeAgent()
    messages = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "partial text",
            "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "f", "arguments": "{}"}}
            ],
        },
    ]

    finalize_turn(
        agent,
        final_response="Here is your answer.",
        api_call_count=3,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="t",
        turn_id="tid",
        user_message="q",
        original_user_message="q",
        _should_review_memory=False,
        _turn_exit_reason="text_response(final)",
    )

    assert agent.persisted_messages[-1]["content"] == "partial text"


def test_fill_pops_db_persisted_marker_for_durable_rewrite(monkeypatch):
    """The incremental tool-call persist stamps ``_db_persisted`` on the row.

    If finalize_turn fills the tail's content but leaves the marker, the next
    ``_flush_messages_to_session_db`` skips the row and the durable SQLite
    store keeps ``content=""`` — so ``/resume`` reloads the empty content and
    the bug resurfaces cross-session. The fix pops the marker so the filled
    content is re-written.
    """
    agent = FakeAgent()
    messages = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "t1", "type": "function",
                 "function": {"name": "f", "arguments": "{}"}}
            ],
            "_db_persisted": True,  # stamped by conversation_loop.py:4990
        },
    ]

    finalize_turn(
        agent,
        final_response="Here is your answer.",
        api_call_count=3,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="t",
        turn_id="tid",
        user_message="q",
        original_user_message="q",
        _should_review_memory=False,
        _turn_exit_reason="text_response(final)",
    )

    persisted = agent.persisted_messages
    assert persisted is not None
    assert persisted[-1]["content"] == "Here is your answer."
    assert persisted[-1]["tool_calls"]
    assert "_db_persisted" not in persisted[-1], (
        "marker must be popped so the next flush re-writes the filled content"
    )


def test_empty_response_exhausted_does_not_persist_reasoning_excerpt(monkeypatch):
    """A delivery-only reasoning excerpt must not be persisted as an assistant message.

    Regression: when ``_turn_exit_reason == "empty_response_exhausted"``, the
    ``final_response`` is a labeled reasoning excerpt (e.g. "⚠️ The model
    produced only internal reasoning…") that is for the user's eyes only.
    Appending it as a persisted assistant message makes future "continue" turns
    replay the reasoning as if it were a real response, causing empty-response
    loops.

    The tail is a non-assistant (user) message — the unconditional ``_tail_role``
    check would have appended the excerpt before this guard.
    """
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    agent = FakeAgent()
    reasoning_excerpt = "⚠️ The model produced only internal reasoning without emitting a visible response."
    messages = [
        {"role": "user", "content": "think step by step"},
    ]

    result = finalize_turn(
        agent,
        final_response=reasoning_excerpt,
        api_call_count=5,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message="think step by step",
        original_user_message="think step by step",
        _should_review_memory=False,
        _turn_exit_reason="empty_response_exhausted",
    )

    # Guard: the reasoning excerpt must NOT appear as an assistant message
    # in either the returned transcript or the durable snapshot.
    assert not any(
        m.get("role") == "assistant"
        and reasoning_excerpt in (m.get("content") or "")
        for m in result["messages"]
    ), "reasoning excerpt leaked into returned transcript as assistant message"

    persisted = agent.persisted_messages
    assert persisted is not None
    assert not any(
        m.get("role") == "assistant"
        and reasoning_excerpt in (m.get("content") or "")
        for m in persisted
    ), "reasoning excerpt leaked into durable persisted messages"

    # Total assistant messages should not increase — the only assistant message
    # is whatever was already in the transcript.
    assert sum(1 for m in result["messages"] if m.get("role") == "assistant") == 0, (
        "guard created an unexpected assistant message in the transcript"
    )
    assert sum(1 for m in persisted if m.get("role") == "assistant") == 0, (
        "guard created an unexpected assistant message in the persisted store"
    )


def test_empty_response_exhausted_still_persists_under_normal_exit(monkeypatch):
    """Delivery-only reasoning guard does NOT block normal-turn persistence.

    When ``_turn_exit_reason`` is *not* ``"empty_response_exhausted"``, the
    ``final_response`` MUST still be appended as an assistant message when the
    tail is a non-assistant row, preserving the invariant that every delivered
    response has a closing assistant row in the transcript (#43849/#44100).
    """
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    agent = FakeAgent()
    messages = [
        {"role": "user", "content": "do it"},
    ]

    result = finalize_turn(
        agent,
        final_response="Here is your answer.",
        api_call_count=2,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message="do it",
        original_user_message="do it",
        _should_review_memory=False,
        _turn_exit_reason="text_response(finish_reason=stop)",
    )

    assert result["messages"][-1] == {"role": "assistant", "content": "Here is your answer."}
    persisted = agent.persisted_messages
    assert persisted is not None
    assert persisted[-1] == {"role": "assistant", "content": "Here is your answer."}
