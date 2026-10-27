"""MLX-backed local speech-to-text provider (Apple Silicon).

Runs transcription on the GPU via Apple's MLX runtime instead of the CPU-bound
faster-whisper / whisper.cpp path. On Apple Silicon this is typically several
times faster and leaves the CPU idle for other work.

Two model families are supported, both selected by the ``model`` string:

* ``mlx-community/whisper-*`` (and any local path holding a Whisper checkpoint)
  -> handled by :mod:`mlx_whisper`.
* Ming 3.0 ASR / Granite Speech / other ``mlx-audio`` checkpoints
  -> handled by :mod:`mlx_audio.stt`.

The provider is entirely local: no audio leaves the machine, so it is exempt
from Hermes's remote upload cap and is safe to use on private recordings.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Env var holding an override for the model repository/path.
MLX_STT_MODEL_ENV = "HERMES_MLX_STT_MODEL"

# Model name fragments that identify an mlx-audio checkpoint rather than a
# Whisper one. Kept lowercase and substring-matched so ``Ming-3.0-asr-tiny-4bit``
# and ``mlx-community/granite-speech-5.0-2b`` both resolve correctly.
_MLX_AUDIO_HINTS = (
    "ming-",
    "ming3",
    "granite-speech",
    "granite_speech",
    "phonon",
)

# Local model directories checked before falling back to the Hub. Lets an
# offline / air-gapped install point Hermes at a pre-staged checkpoint.
_LOCAL_MODEL_ROOTS = (
    Path.home() / ".hermes" / "models",
    Path.home() / ".cache" / "mlx-whisper",
)


def _mlx_available() -> bool:
    """Whether the MLX runtime is importable on this machine."""
    if os.uname().sysname != "Darwin":  # pragma: no cover - platform guard
        return False
    try:
        import importlib.util

        return importlib.util.find_spec("mlx") is not None
    except Exception:  # pragma: no cover - defensive
        return False


def _local_snapshot(repo_id: str) -> Optional[str]:
    """Return a staged local copy of *repo_id* if one is already on disk.

    Downloading from the Hub repeatedly re-hits the xet CAS, which frequently
    returns 401 and forces a multi-gigabyte re-download. Preferring a staged
    copy keeps transcription working offline and avoids that failure mode.
    """
    tail = repo_id.split("/")[-1]
    for root in _LOCAL_MODEL_ROOTS:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if child.name == tail or child.name == repo_id:
                if (child / "config.json").is_file():
                    return str(child)
    return None


def _resolve_model(model_name: Optional[str]) -> str:
    """Resolve the effective model: explicit > env var > a staged local copy."""
    if model_name:
        staged = _local_snapshot(model_name)
        return staged or model_name
    env = os.environ.get(MLX_STT_MODEL_ENV)
    if env:
        return _local_snapshot(env) or env
    for root in _LOCAL_MODEL_ROOTS:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "config.json").is_file():
                return str(child)
    return "mlx-community/whisper-large-v3-turbo"


def _is_mlx_audio_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return any(hint in lowered for hint in _MLX_AUDIO_HINTS)


def _to_16k_mono(source: str) -> str:
    """Return a 16 kHz mono WAV path for *source*.

    mlx-audio's ASR models expect 16 kHz mono input. Uses ffmpeg when present
    and falls back to the original file if conversion is not possible.
    """
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return source
    out = os.path.join(tempfile.mkdtemp(prefix="hermes-mlx-stt-"), "audio.wav")
    try:
        subprocess.run(
            [ffmpeg, "-y", "-i", source, "-ar", "16000", "-ac", "1", out],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.debug("mlx STT: ffmpeg conversion failed (%s); using original", exc)
        return source
    return out if os.path.isfile(out) else source


def transcribe_mlx(
    file_path: str,
    model_name: Optional[str] = None,
    *,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
) -> dict[str, Any]:
    """Transcribe *file_path* locally with MLX. Returns a Hermes transcript dict."""
    if not _mlx_available():
        return {
            "success": False,
            "transcript": "",
            "error": "mlx is not available (requires Apple Silicon with the 'mlx' package)",
        }

    model = _resolve_model(model_name)
    audio = _to_16k_mono(file_path)

    try:
        if _is_mlx_audio_model(model):
            text = _transcribe_mlx_audio(audio, model, language, prompt)
        else:
            text = _transcribe_mlx_whisper(audio, model, language, prompt)
    except Exception as exc:
        logger.warning("mlx STT failed: %s", exc)
        return {
            "success": False,
            "transcript": "",
            "error": f"mlx transcription failed: {exc}",
        }

    if not text:
        return {
            "success": False,
            "transcript": "",
            "error": "mlx returned an empty transcript",
        }
    return {"success": True, "transcript": text, "provider": "mlx", "model": model}


def _transcribe_mlx_whisper(
    audio: str, model: str, language: Optional[str], prompt: Optional[str]
) -> str:
    import mlx_whisper

    kwargs: dict[str, Any] = {"path_or_hf_repo": model}
    if language and language.lower() not in ("auto", ""):
        kwargs["language"] = language
    if prompt:
        kwargs["initial_prompt"] = prompt
    result = mlx_whisper.transcribe(audio, **kwargs)
    return (result.get("text") or "").strip()


def _transcribe_mlx_audio(
    audio: str, model: str, language: Optional[str], prompt: Optional[str]
) -> str:
    from mlx_audio.stt.generate import generate_transcription, load_model

    loaded = load_model(model)
    kwargs: dict[str, Any] = {}
    if language and language.lower() not in ("auto", ""):
        kwargs["language"] = language
    if prompt:
        kwargs["context"] = prompt
    result = generate_transcription(loaded, audio=audio, **kwargs)
    text = getattr(result, "text", None)
    if text is None and isinstance(result, dict):
        text = result.get("text")
    return (text or "").strip()
