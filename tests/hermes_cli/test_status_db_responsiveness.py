"""Advisory database inspection cannot perform blocking I/O on the HTTP loop."""
import asyncio
import threading

from hermes_state import SessionDB


def test_fts_status_opens_database_off_loop_and_keeps_profile(tmp_path, monkeypatch):
    from hermes_cli.web_routers.status import _advisory_pressure
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override

    home = tmp_path / 'secondary'
    home.mkdir()
    with SessionDB(db_path=home / 'state.db'):
        pass
    opened = []
    original = SessionDB._open_read_only

    def read_only(db, *args, **kwargs):
        opened.append((threading.current_thread(), str(db.db_path)))
        return original(db, *args, **kwargs)

    monkeypatch.setattr(SessionDB, '_open_read_only', read_only)
    token = set_hermes_home_override(str(home))
    try:
        status = {}
        asyncio.run(_advisory_pressure(status, home))
    finally:
        reset_hermes_home_override(token)
    assert opened, 'advisory status did not inspect the profile database'
    assert all(thread is not threading.current_thread() for thread, _ in opened), (
        'advisory status opened SQLite on the event loop')
    assert all(path == str(home / 'state.db') for _, path in opened)
    assert 'memory' in status and 'disk' in status
