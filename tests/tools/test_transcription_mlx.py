"""Tests for the native MLX STT provider."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools import transcription_tools
from tools.transcription_mlx import (
    MLX_STT_MODEL_ENV,
    _is_mlx_audio_model,
    _resolve_model,
    transcribe_mlx,
)


@pytest.fixture(autouse=True)
def _isolate_local_model_roots(tmp_path, monkeypatch):
    """Keep tests independent of whatever checkpoints are staged on this machine."""
    from tools import transcription_mlx as mlx_mod

    monkeypatch.setattr(mlx_mod, "_LOCAL_MODEL_ROOTS", (tmp_path / "no-models",))


def test_mlx_provider_is_registered_as_builtin():
    """The provider must be in both builtin registries (drift test enforces sync)."""
    from agent.transcription_registry import _BUILTIN_NAMES

    assert "mlx" in transcription_tools.BUILTIN_STT_PROVIDERS
    assert "mlx" in _BUILTIN_NAMES


def test_mlx_is_treated_as_local_provider():
    """MLX runs on-device, so it must be exempt from the remote upload cap."""
    assert transcription_tools._is_local_stt_provider("mlx", {}) is True


def test_mlx_dispatch_routes_to_handler():
    with mock.patch.object(
        transcription_tools,
        "_transcribe_mlx",
        return_value={"success": True, "transcript": "hi"},
    ) as h:
        out = transcription_tools._dispatch_stt_provider("/tmp/a.wav", "mlx", {})
    assert out["transcript"] == "hi"
    h.assert_called_once()


def test_mlx_audio_model_detection():
    assert _is_mlx_audio_model("mlx-community/Ming-3.0-asr-tiny-4bit") is True
    assert _is_mlx_audio_model("mlx-community/granite-speech-5.0-2b-4bit") is True
    assert _is_mlx_audio_model("mlx-community/granite_speech_5_ctc") is True
    assert _is_mlx_audio_model("mlx-community/whisper-large-v3-turbo") is False
    assert _is_mlx_audio_model("/Users/me/models/Mage-VL-8bit") is False


def test_resolve_model_prefers_explicit_then_env(monkeypatch, tmp_path):
    monkeypatch.setenv(MLX_STT_MODEL_ENV, "env-model")
    assert _resolve_model("explicit-model") == "explicit-model"
    assert _resolve_model(None) == "env-model"


def test_local_snapshot_prefers_staged_copy(tmp_path, monkeypatch):
    """A staged checkpoint must win over the Hub id (avoids xet 401 re-downloads)."""
    from tools import transcription_mlx as mlx_mod

    staged = tmp_path / "Ming-3.0-asr-tiny-4bit"
    staged.mkdir()
    (staged / "config.json").write_text("{}")
    monkeypatch.setattr(mlx_mod, "_LOCAL_MODEL_ROOTS", (tmp_path,))
    assert mlx_mod._local_snapshot("mlx-community/Ming-3.0-asr-tiny-4bit") == str(
        staged
    )
    assert mlx_mod._local_snapshot("mlx-community/does-not-exist") is None
    resolved = mlx_mod._resolve_model("mlx-community/Ming-3.0-asr-tiny-4bit")
    assert resolved == str(staged)


def test_transcribe_mlx_unavailable_returns_error(monkeypatch):
    monkeypatch.setattr("tools.transcription_mlx._mlx_available", lambda: False)
    out = transcribe_mlx("/tmp/a.wav")
    assert out["success"] is False
    assert "mlx is not available" in out["error"]


def test_transcribe_mlx_whisper_path(monkeypatch):
    monkeypatch.setattr("tools.transcription_mlx._mlx_available", lambda: True)
    monkeypatch.setattr("tools.transcription_mlx._to_16k_mono", lambda p: p)
    fake = mock.MagicMock()
    fake.transcribe.return_value = {"text": "  hello world  "}
    fake_mod = mock.MagicMock()
    fake_mod.transcribe = fake.transcribe
    with mock.patch.dict(sys.modules, {"mlx_whisper": fake_mod}):
        out = transcribe_mlx("/tmp/a.wav", "mlx-community/whisper-large-v3-turbo")
    assert out["success"] is True
    assert out["transcript"] == "hello world"
    assert out["provider"] == "mlx"


def test_transcribe_mlx_audio_path(monkeypatch):
    monkeypatch.setattr("tools.transcription_mlx._mlx_available", lambda: True)
    monkeypatch.setattr("tools.transcription_mlx._to_16k_mono", lambda p: p)

    class Result:
        text = " ming output "

    gen_mod = mock.MagicMock()
    gen_mod.load_model.return_value = mock.MagicMock()
    gen_mod.generate_transcription.return_value = Result()
    stt_mod = mock.MagicMock()
    stt_mod.generate = gen_mod
    with mock.patch.dict(
        sys.modules,
        {
            "mlx_audio": mock.MagicMock(),
            "mlx_audio.stt": stt_mod,
            "mlx_audio.stt.generate": gen_mod,
        },
    ):
        out = transcribe_mlx("/tmp/a.wav", "mlx-community/Ming-3.0-asr-tiny-4bit")
    assert out["success"] is True
    assert out["transcript"] == "ming output"


def test_transcribe_mlx_empty_transcript_is_error(monkeypatch):
    monkeypatch.setattr("tools.transcription_mlx._mlx_available", lambda: True)
    monkeypatch.setattr("tools.transcription_mlx._to_16k_mono", lambda p: p)
    fake_mod = mock.MagicMock()
    fake_mod.transcribe.return_value = {"text": "  "}
    with mock.patch.dict(sys.modules, {"mlx_whisper": fake_mod}):
        out = transcribe_mlx("/tmp/a.wav", "mlx-community/whisper-large-v3-turbo")
    assert out["success"] is False
    assert "empty transcript" in out["error"]
