"""Delegated-child marker leak via the shared bash snapshot.

Regression coverage for the bug where a ``delegate_task`` child's terminal
command dumped ``HERMES_DELEGATED_CHILD_CONTEXT=1`` (stamped onto its Popen env
by ``_scrub_delegated_child_kanban_env``) into the shared session snapshot via
``export -p``. Every later command from ANY session then ``source``d the marker,
so the Kanban CLI/watchdog in a perfectly ordinary parent shell failed closed
with "delegate_task child contexts cannot mutate Kanban tasks or boards"
until the gateway restarted. Same bug class as the HERMES_SESSION_ID snapshot
leak (see test_snapshot_session_id_leak.py); the marker is re-stamped fresh on
every delegated command, so excluding it from the snapshot loses nothing.
"""

import os
import re
import subprocess
import sys
import tempfile

import pytest

from tools.environments.base import (
    _SNAPSHOT_EXCLUDED_ENV_REGEX,
    _export_dump_excluding_session_vars,
)

# The marker name is a convention; define it here since agent.delegation_context
# may not exist on all branches.
DELEGATED_CHILD_ENV_MARKER = "HERMES_DELEGATED_CHILD_CONTEXT"


def test_regex_excludes_delegated_marker():
    rx = re.compile(_SNAPSHOT_EXCLUDED_ENV_REGEX)
    line = f'declare -x {DELEGATED_CHILD_ENV_MARKER}="1"'
    assert rx.search(line), "delegated-child marker must be excluded from the snapshot"


def test_export_snippet_unsets_delegated_marker():
    snippet = _export_dump_excluding_session_vars("/tmp/snap.tmp.$BASHPID")
    assert DELEGATED_CHILD_ENV_MARKER in snippet


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX bash snapshot path")
def test_snapshot_dump_strips_delegated_marker():
    """A delegated child's env dump must not persist the lineage marker."""
    snap = tempfile.mktemp()
    snippet = _export_dump_excluding_session_vars(snap)
    env = dict(os.environ)
    env[DELEGATED_CHILD_ENV_MARKER] = "1"
    env["MY_USER_VAR"] = "keepme"
    try:
        subprocess.run(["bash", "-c", snippet], env=env, check=True)
        with open(snap) as f:
            content = f.read()
        assert DELEGATED_CHILD_ENV_MARKER not in content
        # User exports still persist — the exclusion is surgical.
        assert "MY_USER_VAR" in content
    finally:
        if os.path.exists(snap):
            os.unlink(snap)


def test_regex_excludes_multiple_hermes_vars():
    """All session/cron/delegation markers are excluded together."""
    rx = re.compile(_SNAPSHOT_EXCLUDED_ENV_REGEX)
    assert rx.search('declare -x HERMES_SESSION_ID="abc"')
    assert rx.search('declare -x HERMES_UI_SESSION_ID="xyz"')
    assert rx.search('declare -x HERMES_CRON_AUTO_DELIVER_ALL="1"')
    assert rx.search('declare -x HERMES_DELEGATED_CHILD_CONTEXT="1"')
    # Non-matching vars should NOT be excluded
    assert rx.search('declare -x PATH="/usr/bin"') is None
    assert rx.search('declare -x HOME="/Users/test"') is None


def test_export_snippet_unsets_all_markers():
    """The shell snippet unsets every marker variable."""
    snippet = _export_dump_excluding_session_vars("/tmp/snap.tmp.$BASHPID")
    assert "HERMES_SESSION_*" in snippet
    assert "HERMES_CRON_AUTO_DELIVER_*" in snippet
    assert "HERMES_UI_SESSION_ID" in snippet
    assert "HERMES_DELEGATED_CHILD_CONTEXT" in snippet


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX bash snapshot path")
def test_snapshot_preserves_other_hermes_vars():
    """Non-session HERMES_ vars like HERMES_HOME should NOT be stripped."""
    snap = tempfile.mktemp()
    snippet = _export_dump_excluding_session_vars(snap)
    env = dict(os.environ)
    env["HERMES_DELEGATED_CHILD_CONTEXT"] = "1"
    env["HERMES_HOME"] = "/custom/hermes/home"
    try:
        subprocess.run(["bash", "-c", snippet], env=env, check=True)
        with open(snap) as f:
            content = f.read()
        assert "HERMES_DELEGATED_CHILD_CONTEXT" not in content
        assert "/custom/hermes/home" in content
    finally:
        if os.path.exists(snap):
            os.unlink(snap)
