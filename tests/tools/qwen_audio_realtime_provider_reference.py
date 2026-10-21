"""Realtime speech-to-speech voice provider for Alibaba Bailian Qwen-Audio.

Shape follows Hermes' provider ABCs (``agent.tts_provider.TTSProvider`` /
``agent.transcription_provider.TranscriptionProvider``) so this can be lifted into
``agent/realtime_voice_provider.py`` when upstream PR #101808 lands.

Wire facts, all measured on this box (2026-10-21) — none of them are guessable:

* The endpoint REQUIRES the model as a query parameter::

      wss://{host}/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus

  Omitting ``?model=`` returns **404**, not 403/401, which reads like "no
  permission" and sends you down the wrong path entirely.

* The first frame MUST be ``{"type": "session.update", ...}``. A bare
  ``{"modalities": [...]}`` is rejected with
  ``Unsupported or unknown event type:`` (the type field arrives empty).

* Audio in is **16 kHz** / 16-bit / mono; audio out is **24 kHz**. Feeding the
  mic at 24 kHz gets you a slowed-down, pitch-shifted model.

* Turn detection has three modes. ``smart_turn`` fuses acoustic + semantic
  boundary detection so filler sounds ("嗯", "啊") never open a turn — that is
  the right default for duplex. ``server_vad`` uses the official 400-800 ms
  window (800 default). ``push-to-talk`` is ``turn_detection: null`` and the
  client owns commit + ``response.create``.

* Token Plan has its own gateway (``token-plan.<region>.maas.aliyuncs.com``) and
  its own key; the pay-as-you-go gateway is ``{WorkspaceId}.<region>.maas…``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import queue
import ssl
import subprocess
import threading
import time
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen-audio-3.0-realtime-plus"
SR_IN = 16000          # official input spec
SR_OUT = 24000         # official output spec
FRAME_MS = 40          # per-append cadence


class RealtimeVoiceError(RuntimeError):
    """Raised for upstream handshake / protocol failures."""


class QwenAudioRealtimeSession:
    """One live WebSocket conversation.

    Owns the mic pump and the speaker. Callers drive it with :meth:`push_audio`
    (or let :meth:`run_microphone` do it) and read finished turns from
    :attr:`turns`.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = DEFAULT_MODEL,
        voice: Optional[str] = None,
        instructions: str = "",
        turn_mode: str = "smart",
        vad_threshold: float = 0.5,
        silence_ms: int = 800,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.voice = voice
        self.instructions = instructions
        self.turn_mode = turn_mode
        self.vad_threshold = vad_threshold
        self.silence_ms = silence_ms
        self.timeout = timeout

        self.ws = None
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self._opened = threading.Event()

        self.transcript: list[str] = []      # what the user said this turn
        self.reply: list[str] = []           # what the model said
        self.turn_done = threading.Event()
        self.audio_done = threading.Event()
        self.turns: queue.Queue[dict[str, Any]] = queue.Queue()
        self.audio_chunks: list[bytes] = []
        self.error: Optional[str] = None
        self.events: dict[str, int] = {}
        self.on_audio: Optional[Callable[[bytes], None]] = None
        self.on_turn: Optional[Callable[[str, str], None]] = None

    # -- wire -------------------------------------------------------------
    def url(self) -> str:
        # ?model= is mandatory; the endpoint 404s without it.
        return f"{self.base_url}/api-ws/v1/realtime?model={self.model}"

    def connect(self) -> None:
        from websocket import create_connection

        self.ws = create_connection(
            self.url(),
            sslopt={"cert_reqs": ssl.CERT_NONE},
            timeout=self.timeout,
            # ONLY this header — a second X-DashScope-* header is not accepted.
            header=[f"Authorization: Bearer {self.api_key}"],
        )
        self._send({"type": "session.update", "session": self._session_config()})
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if not self._opened.wait(25):
            raise RealtimeVoiceError("upstream never sent session.created")

    def _session_config(self) -> dict[str, Any]:
        cfg: dict[str, Any] = {
            "modalities": ["text", "audio"],
            "input_audio_transcription": {"model": "fun-asr"},
        }
        if self.instructions:
            cfg["instructions"] = self.instructions
        if self.voice:
            cfg["voice"] = self.voice
        if self.turn_mode == "smart":
            cfg["turn_detection"] = {"type": "smart_turn"}
        elif self.turn_mode == "vad":
            cfg["turn_detection"] = {
                "type": "server_vad",
                "threshold": self.vad_threshold,
                "silence_duration_ms": self.silence_ms,
            }
        else:                       # push-to-talk
            cfg["turn_detection"] = None
        return cfg

    def _send(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if self.ws is None:
                raise RealtimeVoiceError("session is closed")
            self.ws.send(json.dumps(payload, ensure_ascii=False))

    def close(self) -> None:
        with self._lock:
            if self.ws is not None:
                try:
                    self.ws.close()
                except Exception:
                    pass
                self.ws = None

    # -- inbound ----------------------------------------------------------
    _HANDLERS: dict[str, Any] = {}

    def _read_loop(self) -> None:
        while True:
            try:
                raw = self.ws.recv()
            except Exception as exc:
                if not self.error:
                    self.error = f"{type(exc).__name__}: {exc}"
                self.turn_done.set()
                return
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            t = ev.get("type", "?")
            self.events[t] = self.events.get(t, 0) + 1

            handler = self._HANDLERS.get(t)
            if handler is not None:
                handler(self, ev)

    # -- event handlers (table dispatch, not an if/elif ladder) ------------
    def _on_session_ready(self, _ev: dict[str, Any]) -> None:
        self._opened.set()

    def _on_error(self, ev: dict[str, Any]) -> None:
        err = ev.get("error", {})
        self.error = f"{err.get('code')}: {err.get('message')}"

    def _on_transcript(self, ev: dict[str, Any]) -> None:
        heard = (ev.get("transcript") or "").strip()
        if heard:
            self.transcript.append(heard)

    def _on_reply_delta(self, ev: dict[str, Any]) -> None:
        self.reply.append(ev.get("delta", ""))

    def _on_audio_delta(self, ev: dict[str, Any]) -> None:
        pcm = base64.b64decode(ev.get("delta", ""))
        if not pcm:
            return
        self.audio_chunks.append(pcm)
        if self.on_audio:                          # play as it arrives
            try:
                self.on_audio(pcm)
            except Exception as exc:
                logger.warning("on_audio failed: %s", exc)

    def _on_audio_done(self, _ev: dict[str, Any]) -> None:
        self.audio_done.set()

    def _on_response_done(self, _ev: dict[str, Any]) -> None:
        threading.Thread(target=self._finish_turn, daemon=True).start()

    def _finish_turn(self) -> None:
        # Wait for the audio tail instead of sleeping: the server sends
        # response.done before the last response.audio.delta frames have landed.
        self.audio_done.wait(5.0)
        heard = "".join(self.transcript).strip()
        said = "".join(self.reply).strip()
        self.turns.put({"heard": heard, "reply": said,
                        "audio": b"".join(self.audio_chunks)})
        if self.on_turn:
            try:
                self.on_turn(heard, said)
            except Exception as exc:
                logger.warning("on_turn failed: %s", exc)
        self.transcript.clear()
        self.reply.clear()
        self.audio_chunks.clear()
        self.audio_done.clear()
        self.turn_done.set()

    # -- outbound ---------------------------------------------------------
    def push_audio(self, pcm_16k: bytes) -> None:
        self._send({"type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm_16k).decode()})

    def commit(self) -> None:
        """push-to-talk only: close the turn and ask for an answer."""
        self._send({"type": "input_audio_buffer.commit"})
        self._send({"type": "response.create",
                    "response": {"modalities": ["text", "audio"]}})

    def wait_turn(self, timeout: Optional[float] = None) -> dict[str, Any]:
        try:
            return self.turns.get(timeout=timeout or self.timeout)
        except queue.Empty:
            return {"heard": "", "reply": "", "audio": b"", "timeout": True}

    # -- mic / speaker ----------------------------------------------------
    def run_microphone(
        self,
        device: int,
        on_turn: Optional[Callable[[str, str], None]] = None,
        stop: Optional[threading.Event] = None,
    ) -> None:
        """Stream the mic until ``stop`` is set. Never stops mid-stream — the
        server only closes a turn while audio keeps arriving."""
        if on_turn:
            self.on_turn = on_turn
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
               "-f", "avfoundation", "-i", f":{device}",
               "-f", "s16le", "-acodec", "pcm_s16le",
               "-ac", "1", "-ar", str(SR_IN), "-"]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        frame = int(SR_IN * FRAME_MS / 1000) * 2
        stop = stop or threading.Event()
        try:
            while not stop.is_set():
                data = proc.stdout.read(frame)
                if not data or len(data) < frame:
                    if proc.poll() is not None:
                        break
                    continue
                self.push_audio(data)
        finally:
            proc.kill()
            self.close()


def play_pcm(pcm: bytes) -> None:
    """Play 24 kHz mono s16le PCM through afplay (blocking)."""
    if not pcm:
        return
    proc = subprocess.Popen(
        ["afplay", "-q", "-f", "s16le", "-r", str(SR_OUT), "-c", "1", "-"],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        proc.stdin.write(pcm)
        proc.stdin.flush()
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass


QwenAudioRealtimeSession._HANDLERS = {
    "session.created": QwenAudioRealtimeSession._on_session_ready,
    "session.updated": QwenAudioRealtimeSession._on_session_ready,
    "error": QwenAudioRealtimeSession._on_error,
    "conversation.item.input_audio_transcription.completed":
        QwenAudioRealtimeSession._on_transcript,
    "response.audio_transcript.delta": QwenAudioRealtimeSession._on_reply_delta,
    "response.audio.delta": QwenAudioRealtimeSession._on_audio_delta,
    "response.audio.done": QwenAudioRealtimeSession._on_audio_done,
    "response.done": QwenAudioRealtimeSession._on_response_done,
}


# --------------------------------------------------------------------------
# Hermes plugin provider
# --------------------------------------------------------------------------
class QwenAudioRealtimeProvider:
    """Realtime speech-to-speech provider.

    Mirrors the surface of ``agent.tts_provider.TTSProvider``: ``name`` plus the
    capability introspection the dispatcher reads. When upstream #101808 lands
    this class gains :meth:`create_session` to satisfy its
    ``RealtimeVoiceProvider`` ABC verbatim.
    """

    name = "qwen_audio_realtime"
    streams_pcm = True
    stream_sample_rate = SR_OUT
    input_sample_rate = SR_IN

    def is_available(self) -> bool:
        return bool(self._key())

    def _key(self) -> str:
        return _env_value("QWEN_PLAN_TOKEN") or _env_value("BAILIAN_API_KEY")

    def create_session(self, on_turn=None, **_: Any) -> QwenAudioRealtimeSession:
        """Open a live session (the #101808-shaped entry point)."""
        return build_session_from_config(on_turn=on_turn)

    def default_voice(self) -> Optional[str]:
        return "longanqian"

    def list_voices(self) -> list[dict[str, Any]]:
        return [
            {"id": "longanqian", "display": "龙安千千", "language": "zh"},
            {"id": "longanlingxin", "display": "龙安灵心", "language": "zh"},
            {"id": "longanlingxi", "display": "龙安灵溪", "language": "zh"},
            {"id": "longanxiaoxin", "display": "龙安小新", "language": "zh"},
            {"id": "longanlufeng", "display": "龙安鲁风", "language": "zh"},
        ]


# --------------------------------------------------------------------------
# Hermes plugin registration
# --------------------------------------------------------------------------
def _env_value(name: str) -> str:
    """Read a secret from ``$HERMES_HOME/.env`` without echoing it.

    Honours ``HERMES_HOME`` rather than hardcoding ``~/.hermes`` so a test (or a
    profile) never touches the real home. Falls back to the process env.
    """
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    try:
        with open(os.path.join(home, ".env"), errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get(name, "")


def build_session_from_config(
    voice_config: Optional[dict[str, Any]] = None,
    *,
    on_turn: Optional[Callable[[str, str], None]] = None,
) -> QwenAudioRealtimeSession:
    """Build a session from ``voice.realtime.qwen_audio`` config."""
    if voice_config is None:
        from hermes_cli.config import load_config
        voice_config = load_config().get("voice") or {}
    section = (voice_config.get("realtime") or {}).get("qwen_audio") or {}

    key = (section.get("api_key") or "").strip() or _env_value(
        section.get("api_key_env") or "QWEN_PLAN_TOKEN")
    if not key:
        raise RealtimeVoiceError(
            "no key: set voice.realtime.qwen_audio.api_key or QWEN_PLAN_TOKEN in ~/.hermes/.env")

    base_url = (section.get("base_url")
                or "wss://token-plan.cn-beijing.maas.aliyuncs.com")
    model = section.get("model") or DEFAULT_MODEL
    voice = section.get("voice") or "longanqian"
    turn_mode = section.get("turn_mode") or "smart"

    sess = QwenAudioRealtimeSession(
        api_key=key, base_url=base_url, model=model, voice=voice,
        instructions=section.get("instructions") or "",
        turn_mode=turn_mode,
        vad_threshold=float(section.get("vad_threshold", 0.5)),
        silence_ms=int(section.get("silence_ms", 800)),
    )
    sess.on_turn = on_turn
    sess.on_audio = Speaker().play
    return sess


class Speaker:
    """Plays each audio chunk as it arrives — this is what keeps latency low.

    A fresh ``afplay`` per chunk would add tens of ms of process startup to every
    frame, so the pipe is kept open and reused.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None

    def _ensure(self) -> Optional[subprocess.Popen]:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                ["afplay", "-q", "-f", "s16le", "-r", str(SR_OUT), "-c", "1", "-"],
                stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return self._proc

    def play(self, pcm: bytes) -> None:
        if not pcm:
            return
        with self._lock:
            proc = self._ensure()
            try:
                proc.stdin.write(pcm)
                proc.stdin.flush()
            except (BrokenPipeError, OSError, AttributeError):
                self._proc = None

    def close(self) -> None:
        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.stdin.close()
                    self._proc.terminate()
                except Exception:
                    pass
                self._proc = None


def register(ctx: Any) -> None:
    """Hermes plugin entry point.

    Uses #101808's ``ctx.register_realtime_voice_provider`` when the upstream
    contract is present; otherwise falls back to the voice-command plugin hook so
    the provider is at least reachable from ``/voice`` on this checkout.
    """
    for hook in ("register_realtime_voice_provider",):
        fn = getattr(ctx, hook, None)
        if fn is not None:
            fn(QwenAudioRealtimeProvider())
            logger.info("registered qwen_audio_realtime via %s", hook)
            return
    logger.warning(
        "no realtime-voice provider hook on this Hermes build (#101808 not merged); "
        "use qwen_audio_realtime directly")
