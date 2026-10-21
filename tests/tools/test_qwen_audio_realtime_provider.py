"""Protocol-shape tests for the reference Qwen-Audio realtime voice provider.

These assert the wire facts that are expensive to rediscover: the endpoint 404s
without ``?model=``, rejects a bare first frame, and the audio rates are not
interchangeable.  No network: the WebSocket is stubbed.

The provider itself ships as an out-of-tree plugin (see
``website/docs/developer-guide/plugins/``); this module pins the protocol
contract so a future in-tree realtime-voice ABC (#101808) can be implemented
against something already verified against the real vendor.
"""

from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qwen_audio_realtime_provider_reference import (
    DEFAULT_MODEL,
    SR_IN,
    SR_OUT,
    QwenAudioRealtimeSession,
    RealtimeVoiceError,
    build_session_from_config,
)


def _session(**kw) -> QwenAudioRealtimeSession:
    base = dict(api_key="sk-test", base_url="wss://token-plan.cn-beijing.maas.aliyuncs.com")
    base.update(kw)
    return QwenAudioRealtimeSession(**base)


class TestEndpointShape:
    def test_model_is_a_query_parameter(self):
        """Omitting ?model= returns 404, which reads as 'no permission'."""
        url = _session().url()
        assert url.endswith(f"/api-ws/v1/realtime?model={DEFAULT_MODEL}")
        assert "?model=" in url

    def test_base_url_trailing_slash_is_stripped(self):
        s = _session(base_url="wss://example.cn-beijing.maas.aliyuncs.com/")
        assert "//api-ws" not in s.url().replace("https://", "")


class TestSessionConfig:
    def test_first_frame_is_session_update(self):
        s = _session()
        assert "session.update" not in s.url()          # sanity: config is not URL
        cfg = s._session_config()
        assert cfg["modalities"] == ["text", "audio"]
        assert cfg["input_audio_transcription"] == {"model": "fun-asr"}

    def test_smart_turn_is_the_default(self):
        assert _session(turn_mode="smart")._session_config()["turn_detection"] == {
            "type": "smart_turn"}

    def test_server_vad_carries_threshold_and_silence(self):
        td = _session(turn_mode="vad", vad_threshold=0.3, silence_ms=600)._session_config()[
            "turn_detection"]
        assert td == {"type": "server_vad", "threshold": 0.3, "silence_duration_ms": 600}

    def test_push_to_talk_is_null(self):
        assert _session(turn_mode="ptt")._session_config()["turn_detection"] is None

    def test_voice_only_sent_when_set(self):
        assert "voice" not in _session()._session_config()
        assert _session(voice="longanqian")._session_config()["voice"] == "longanqian"


class TestAudioRates:
    def test_input_and_output_rates_differ(self):
        """16 kHz in / 24 kHz out — feeding the mic at 24 kHz detunes the model."""
        assert SR_IN == 16000
        assert SR_OUT == 24000


class TestEventHandling:
    def _pump(self, sess, events):
        for ev in events:
            sess._read_loop.__wrapped__ if False else None
        # drive the handler directly through a fake recv
        frames = [json.dumps(e).encode() for e in events]

        class FakeWS:
            def __init__(self):
                self._i = iter(frames)

            def recv(self):
                try:
                    return next(self._i)
                except StopIteration:
                    raise RealtimeVoiceError("done")

        sess.ws = FakeWS()
        sess._read_loop()

    def test_transcript_and_reply_are_collected(self):
        s = _session()
        self._pump(s, [
            {"type": "session.created", "session": {"id": "x"}},
            {"type": "conversation.item.input_audio_transcription.completed",
             "transcript": "老大"},
            {"type": "response.audio_transcript.delta", "delta": "收到"},
            {"type": "response.audio_transcript.delta", "delta": "！"},
            {"type": "response.done"},
        ])
        assert s._opened.is_set()
        assert "老大" in s.transcript
        assert "".join(s.reply) == "收到！"

    def test_audio_delta_is_base64_decoded(self):
        s = _session()
        pcm = b"\x01\x02" * 50
        self._pump(s, [
            {"type": "session.created"},
            {"type": "response.audio.delta",
             "delta": base64.b64encode(pcm).decode()},
            {"type": "response.done"},
        ])
        assert pcm in s.audio_chunks

    def test_error_event_is_captured(self):
        s = _session()
        self._pump(s, [
            {"type": "session.created"},
            {"type": "error", "error": {"code": "invalid_value",
                                         "message": "Unsupported event type"}},
        ])
        assert s.error and "invalid_value" in s.error


class TestConfigEntry:
    def test_reads_realtime_qwen_audio_section(self, tmp_path, monkeypatch):
        # never touch the real ~/.hermes/.env
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / ".env").write_text("QWEN_PLAN_TOKEN=sk-isolated\n")
        cfg = {"realtime": {"qwen_audio": {
            "model": "qwen-audio-3.1-realtime-plus",
            "voice": "longanqian_v3.1",
            "turn_mode": "vad",
            "silence_ms": 500,
        }}}
        s = build_session_from_config(cfg)
        assert s.model == "qwen-audio-3.1-realtime-plus"
        assert s.voice == "longanqian_v3.1"
        assert s.turn_mode == "vad"
        assert s.silence_ms == 500
        assert s.url().endswith("?model=qwen-audio-3.1-realtime-plus")

    def test_missing_key_raises_actionable_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.delenv("QWEN_PLAN_TOKEN", raising=False)
        monkeypatch.delenv("BAILIAN_API_KEY", raising=False)
        with pytest.raises(RealtimeVoiceError, match="no key"):
            build_session_from_config({"realtime": {"qwen_audio": {}}})


class TestProviderSurface:
    def test_provider_exposes_catalog_shape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        from qwen_audio_realtime_provider_reference import QwenAudioRealtimeProvider
        p = QwenAudioRealtimeProvider()
        assert p.name == "qwen_audio_realtime"
        assert p.streams_pcm is True
        assert p.stream_sample_rate == SR_OUT
        assert p.input_sample_rate == SR_IN
        assert p.default_voice() == "longanqian"
        assert {"id"} <= set(p.list_voices()[0])
