"""Advisory database inspection cannot perform blocking I/O on the HTTP loop."""
import asyncio
import sqlite3
import threading

from hermes_constants import set_hermes_home_override, reset_hermes_home_override


def test_fts_status_opens_database_off_loop_and_keeps_profile(tmp_path, monkeypatch):
    from hermes_cli.web_routers.status import _advisory_pressure

    home = tmp_path / 'secondary'
    home.mkdir()
    # Create a minimal state.db so store_exists returns True for the profile scope.
    conn = sqlite3.connect(str(home / 'state.db'))
    conn.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY)')
    conn.close()

    # Track the thread that calls _fts_rebuild_status (the step that opens state.db).
    # It must not be the event-loop thread — _advisory_pressure runs all blocking
    # steps through run_in_threadpool.
    opened_on = []
    from hermes_cli.web_routers.status import _fts_rebuild_status as _orig_fts

    def tracking_fts():
        opened_on.append(threading.current_thread())
        return _orig_fts()

    monkeypatch.setattr("hermes_cli.web_routers.status._fts_rebuild_status", tracking_fts)

    token = set_hermes_home_override(str(home))
    try:
        status = {}
        asyncio.run(_advisory_pressure(status, home))
    finally:
        reset_hermes_home_override(token)
    assert opened_on, 'advisory status did not inspect the profile database'
    assert all(t is not threading.current_thread() for t in opened_on), (
        'advisory status opened SQLite on the event loop')
    assert 'memory' in status and 'disk' in status
