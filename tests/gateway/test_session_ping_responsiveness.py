"""Connection liveness must not wait for profile terminal-policy disk reads."""
import asyncio
import threading
from dataclasses import replace

import pytest

from tests.gateway.test_hosted_mux_runtime import mux


def test_ping_answers_while_profile_policy_is_unavailable(mux, monkeypatch):
    from gateway.session_controls import AuthorityConnection
    from tools import terminal_scope

    runner, homes, loop, call = mux
    authority = runner.session_authorities.require(homes['alpha'])
    connection = AuthorityConnection(authority, object(), {'user_id': 'owner'})
    release = threading.Event()
    original = terminal_scope.build_profile_terminal_scope

    def held_policy(*args, **kwargs):
        if not release.wait(10):
            raise RuntimeError('policy read was not released')
        return original(*args, **kwargs)

    monkeypatch.setattr(terminal_scope, 'build_profile_terminal_scope', held_policy)
    future = asyncio.run_coroutine_threadsafe(connection.dispatch(
        {'id': 1, 'method': 'ping', 'params': {}}), loop)
    try:
        try:
            # The policy read stays blocked for 10s, so a 5s budget still proves the ping
            # answered without it. (A tighter budget only measures the runner's load.)
            reply = future.result(5)
        except TimeoutError:
            pytest.fail('ping waited for profile policy disk I/O', pytrace=False)
        assert reply == {'jsonrpc': '2.0', 'id': 1, 'result': {'pong': True}}
    finally:
        release.set()
        future.result(15)
        call(connection.close())


def test_ping_keeps_capability_and_parameter_checks(mux):
    from gateway.session_controls import AuthorityConnection

    runner, _, _, call = mux
    connection = AuthorityConnection(runner.session_authority, object(), {'user_id': 'owner'})
    try:
        reply = call(connection.dispatch({'id': 1, 'method': 'ping', 'params': {'extra': True}}))
        assert reply['error']['data']['reason'] == 'invalid_params'
        connection.actor = replace(connection.actor, capabilities=frozenset())
        reply = call(connection.dispatch({'id': 2, 'method': 'ping', 'params': {}}))
        assert reply['error']['data']['reason'] == 'permission_denied'
    finally:
        call(connection.close())
