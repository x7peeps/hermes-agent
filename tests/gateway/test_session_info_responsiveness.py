"""Session metadata and the control socket stay live while token accounting is queued."""
import asyncio
import json
import socket
import threading
from types import SimpleNamespace

from tests.gateway.test_hosted_mux_runtime import mux


def test_session_info_does_not_wait_for_token_writer(mux, monkeypatch):
    from gateway.config import Platform
    from gateway.session import SessionSource
    from gateway.session_authority import LiveSession
    from gateway.session_contract import SessionRef
    from gateway.session_controls import AuthorityConnection
    from gateway import session_local_inventory

    runner, homes, loop, call = mux
    authority = runner.session_authority
    db = authority.db
    db.create_session('probe', source='telegram')
    db.set_session_title('probe', 'Connection probe')
    authority.sessions['probe'] = LiveSession(
        SessionSource(platform=Platform.TELEGRAM, chat_id='probe'), 'probe')
    monkeypatch.setattr(runner, '_resident_agent_for', lambda route: SimpleNamespace(
        model='fixture', provider='custom', tools=[]))
    monkeypatch.setattr(session_local_inventory, 'session_inventory', lambda *args: {})
    connection = AuthorityConnection(authority, object(), {'user_id': 'owner'})
    entered, release = threading.Event(), threading.Event()
    apply_batch = db._apply_token_batch

    def held_batch(batch):
        entered.set()
        if not release.wait(15):
            raise RuntimeError('token writer test was not released')
        return apply_batch(batch)

    monkeypatch.setattr(db, '_apply_token_batch', held_batch)
    future = None
    try:
        db.queue_token_counts('probe', input_tokens=7, output_tokens=3)
        assert entered.wait(5)
        future = asyncio.run_coroutine_threadsafe(connection.info(
            SessionRef(authority.profile_id, 'probe'), {'session_id': 'probe'}), loop)
        # A metadata read has no reason to wait for usage totals to commit.
        try:
            info = future.result(2)
        except TimeoutError:
            import pytest
            pytest.fail('session.info blocked behind the token writer', pytrace=False)
        assert info['title'] == 'Connection probe'
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            from gateway.control_socket import resolve_client_socket_path
            client.connect(str(resolve_client_socket_path(homes['default'])))
            client.sendall(b'{"protocol":1,"id":1,"verb":"identify"}\n')
            data = b''
            while b'\n' not in data:
                chunk = client.recv(65536)
                assert chunk
                data += chunk
            assert json.loads(data)['ok'] is True
    finally:
        release.set()
        if future is not None:
            future.result(15)
        call(connection.close())
    # Exact accounting remains available once the writer finishes.
    assert db.get_session('probe')['input_tokens'] == 7
