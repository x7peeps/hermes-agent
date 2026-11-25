"""Served WebSocket connections must not negotiate permessage-deflate.

uvicorn enables ``ServerPerMessageDeflateFactory`` by default, so every
outgoing frame is zlib-deflated ON the serving event loop, and each
``compressobj().compress()``/``.flush()`` releases and re-takes the GIL.
Under the gateway's normal thread population the re-take waits behind
hundreds of runnable threads, so multi-MB Desktop sync frames stall the
loop in bursts and identify/bootstrap deadlines expire (sampled during a
timeout burst: main thread 57% ``take_gil``, 36% ``zlib_Compress_*``
directly inside ``task_step``). Loopback JSON payloads gain almost
nothing from deflate, so both server builders must turn it off.
"""

import uvicorn

from hermes_cli import web_server
from hermes_cli import web_server_lifecycle


def test_start_server_disables_ws_permessage_deflate(monkeypatch):
    captured: dict = {}

    class _FakeConfig:
        loaded = True

        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        def load(self):
            pass

        class lifespan_class:
            should_exit = False
            state: dict = {}

            def __init__(self, *args):
                pass

    import contextlib

    class _FakeServer:
        should_exit = False
        started = True
        servers: list = []
        lifespan = None

        @staticmethod
        def capture_signals():
            return contextlib.nullcontext()

        async def startup(self, sockets=None):
            pass

        async def main_loop(self):
            pass

        async def shutdown(self, sockets=None):
            pass

    monkeypatch.setattr(uvicorn, "Config", _FakeConfig)
    monkeypatch.setattr(uvicorn, "Server", lambda config: _FakeServer())

    web_server.start_server(host="127.0.0.1", port=0, open_browser=False)

    assert captured["ws_per_message_deflate"] is False


def test_listener_server_disables_ws_permessage_deflate(monkeypatch):
    """build_listener_server (the gateway session listener the Desktop
    backend connects to) must pass the same flag, not only the dashboard.
    """
    monkeypatch.setattr(web_server_lifecycle, "_uvicorn_console_logging", lambda: None)

    config, server = web_server_lifecycle.build_listener_server(
        object(), host="127.0.0.1", port=0, auth_required=False)

    assert config.ws_per_message_deflate is False
    assert server.config is config
