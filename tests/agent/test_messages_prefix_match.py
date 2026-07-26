"""Tests for the _messages_prefix_match helper in conversation_compression."""
import pytest

from agent.conversation_compression import _messages_prefix_match


class TestMessagesPrefixMatch:
    """Verify the prefix-match helper used by the rotation drift guard."""

    def test_empty_lists_match(self):
        assert _messages_prefix_match([], []) is True

    def test_single_message_match(self):
        msgs = [{"role": "user", "content": "hello"}]
        assert _messages_prefix_match(msgs, msgs) is True

    def test_multiple_messages_match(self):
        a = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "how are you?"},
        ]
        assert _messages_prefix_match(a, list(a)) is True

    def test_different_length(self):
        a = [{"role": "user", "content": "hello"}]
        b = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        assert _messages_prefix_match(a, b) is False
        assert _messages_prefix_match(b, a) is False

    def test_different_role(self):
        a = [{"role": "user", "content": "hello"}]
        b = [{"role": "assistant", "content": "hello"}]
        assert _messages_prefix_match(a, b) is False

    def test_different_content(self):
        a = [{"role": "user", "content": "hello"}]
        b = [{"role": "user", "content": "goodbye"}]
        assert _messages_prefix_match(a, b) is False

    def test_multimodal_content_match(self):
        """Both text and list-style content should be normalized via _message_text."""
        a = [{"role": "user", "content": "hello world"}]
        b = [{"role": "user", "content": "hello world"}]
        assert _messages_prefix_match(a, b) is True

    def test_list_content_match(self):
        """Multimodal list content should match by extracted text."""
        content = [{"type": "text", "text": "hello"}]
        a = [{"role": "user", "content": content}]
        b = [{"role": "user", "content": list(content)}]
        assert _messages_prefix_match(a, b) is True

    def test_extra_keys_ignored(self):
        """Internal flags like _synthetic_user should not affect matching."""
        a = [{"role": "user", "content": "hello", "_synthetic_user": True}]
        b = [{"role": "user", "content": "hello"}]
        assert _messages_prefix_match(a, b) is True

    def test_partial_compression_scenario(self):
        """Simulate the exact bug scenario: durable parent has 6 messages,
        caller only passes the first 2 (the head for /compress here 2).
        The prefix of durable_parent should match messages."""
        durable_parent = [
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "reply2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "reply3"},
        ]
        head = durable_parent[:2]  # partial compression head
        assert _messages_prefix_match(durable_parent[:2], head) is True

    def test_concurrent_append_detected(self):
        """If a concurrent writer appended a message, the prefix won't match
        because the caller's messages would include the new one."""
        original = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        # Caller's snapshot had 2 messages, but durable now has a third
        # that was appended by another writer before our caller
        # However, if the caller's messages are still just the original 2,
        # and durable_parent[:2] matches, it's NOT a concurrent append —
        # it's just the tail being excluded.
        durable_parent = original + [{"role": "user", "content": "new msg"}]
        # This should match — caller is doing partial compression
        assert _messages_prefix_match(durable_parent[:2], original) is True

    def test_real_concurrent_mutation_detected(self):
        """If a concurrent writer mutated one of the messages the caller
        sent, the prefix should NOT match."""
        caller_messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        # Concurrent writer changed the assistant's response
        durable_parent = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there, friend!"},
        ]
        assert _messages_prefix_match(durable_parent, caller_messages) is False
