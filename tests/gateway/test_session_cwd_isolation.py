"""Regression test for #69396: gateway session cwd isolation from cron workdir.

When a cron job with ``workdir`` is running, it sets
``os.environ["TERMINAL_CWD"]`` to its workdir (process-global).  A gateway
session created during that window must still use the gateway's launch-time
cwd, not the cron job's workdir.

The fix: ``GatewayRunner._set_session_env`` passes the launch-time cwd to
``set_session_vars``, which pins ``_SESSION_CWD``.  ``resolve_context_cwd()``
checks ``_SESSION_CWD`` before falling through to ``TERMINAL_CWD``.
"""

from __future__ import annotations

import os

import pytest


class TestSessionCwdIsolationFromCron:
    """Verify that a gateway session's _SESSION_CWD is immune to concurrent
    cron-job ``TERMINAL_CWD`` overrides."""

    def test_set_session_env_pins_cwd_independently(self, tmp_path, monkeypatch):
        """Calling set_session_vars with cwd= pins _SESSION_CWD so that
        resolve_context_cwd returns the session cwd even when TERMINAL_CWD
        has been mutated by a concurrent cron job."""
        from agent.runtime_cwd import resolve_context_cwd
        from gateway.session_context import set_session_vars, clear_session_vars

        gateway_cwd = tmp_path / "gateway_cwd"
        gateway_cwd.mkdir()
        cron_workdir = tmp_path / "cron_workdir"
        cron_workdir.mkdir()

        # Pin TERMINAL_CWD to simulate a cron job's workdir override.
        monkeypatch.setenv("TERMINAL_CWD", str(cron_workdir))

        # Set session env with the gateway's launch-time cwd.
        tokens = set_session_vars(
            platform="telegram",
            chat_id="123",
            cwd=str(gateway_cwd),
        )

        try:
            # resolve_context_cwd should prefer _SESSION_CWD over TERMINAL_CWD.
            result = resolve_context_cwd()
            assert result is not None
            assert result.resolve() == gateway_cwd.resolve(), (
                f"Expected gateway launch cwd, but got {result} "
                f"(TERMINAL_CWD={os.environ.get('TERMINAL_CWD')!r})"
            )
        finally:
            clear_session_vars(tokens)

    def test_resolve_context_cwd_falls_through_when_no_session_cwd(self, tmp_path, monkeypatch):
        """When no session cwd is set, resolve_context_cwd falls through to
        TERMINAL_CWD (the cron-compatible path)."""
        from agent.runtime_cwd import resolve_context_cwd

        cron_workdir = tmp_path / "cron_workdir"
        cron_workdir.mkdir()

        # Make sure _SESSION_CWD is not set (no set_session_vars call).
        monkeypatch.setenv("TERMINAL_CWD", str(cron_workdir))

        result = resolve_context_cwd()
        assert result is not None
        assert result.resolve() == cron_workdir.resolve()

    def test_cron_workdir_does_not_affect_session_with_own_cwd(self, tmp_path, monkeypatch):
        """End-to-end: a gateway session with its own cwd is unaffected by
        a simulated cron job mutating TERMINAL_CWD mid-session."""
        from agent.runtime_cwd import resolve_context_cwd
        from gateway.session_context import set_session_vars, clear_session_vars

        gateway_cwd = tmp_path / "gateway_cwd"
        gateway_cwd.mkdir()
        cron_workdir = tmp_path / "cron_workdir"
        cron_workdir.mkdir()

        # Simulate the gateway's launch-time cwd being set initially.
        monkeypatch.setenv("TERMINAL_CWD", str(gateway_cwd))

        tokens = set_session_vars(
            platform="signal",
            chat_id="456",
            cwd=str(gateway_cwd),
        )

        try:
            # Now simulate a cron job starting and overriding TERMINAL_CWD.
            monkeypatch.setenv("TERMINAL_CWD", str(cron_workdir))

            # The session should still see its own cwd.
            result = resolve_context_cwd()
            assert result is not None
            assert result.resolve() == gateway_cwd.resolve(), (
                "Session cwd leaked to cron workdir!"
            )
        finally:
            # Restore TERMINAL_CWD to the gateway's launch cwd.
            monkeypatch.setenv("TERMINAL_CWD", str(gateway_cwd))
            clear_session_vars(tokens)
