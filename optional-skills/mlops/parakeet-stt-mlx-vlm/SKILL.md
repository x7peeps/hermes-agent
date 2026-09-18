---
name: parakeet-stt-mlx-vlm
description: Parakeet/Canary STT locally via mlx-vlm server
version: 1.0.0
author: x7peeps
license: MIT
dependencies: [mlx-vlm>=0.7.1, mlx-audio]
platforms: [macos, linux]
metadata:
  hermes:
    tags: [STT, Parakeet, Canary, mlx-vlm, mlx-audio, local, OpenAI-compatible, Apple Silicon, transcription, nemo]
---

# Parakeet / Canary STT via mlx-vlm — Hermes-ready local speech-to-text

`mlx-vlm` 0.7.1 (released 2026-09-14) ships an **OpenAI-compatible `/v1/audio/transcriptions`
endpoint** in its built-in server, backed by NVIDIA NeMo-alignment speech models
(Parakeet-TDT, Canary-1B). This optional skill wraps that server so a Hermes user
can run high-accuracy, fully-local, GPU-free STT on Apple Silicon (or any MLX-capable
host) with **one command** and **zero code changes to Hermes**.

The integration is configuration-only: point Hermes's built-in `openai` STT provider
at the local `mlx-vlm` server's base URL. No new core tool, no plugin, no
`HERMES_*` env var.

## When to use this

Use this skill when:

- **You want local STT but `faster-whisper` isn't accurate enough on your language**
  (Parakeet-TDT-0.6B-v3 scores higher on common Mandarin / multilingual benchmarks
  than Whisper `small`/`medium`, and is faster on Apple Silicon).
- **You want OpenAI Whisper-level accuracy without sending audio to OpenAI.**
- **You have ≥8 GB unified memory** (Parakeet-TDT-0.6B-v3 in 4-bit ≈ 700 MB; Canary-1B
  in 4-bit ≈ 1.3 GB).
- **You already run `mlx-vlm` for VLM** and want to share the same model server.

Skip this skill if:

- You only need English and `faster-whisper base` is fast enough.
- You don't have an Apple Silicon / MLX-capable host (the server is MLX-bound).
- You need sub-200 ms latency for real-time streaming (this server is request/response,
  not WebSocket realtime — `mlx-vlm` also exposes `/v1/realtime` but it's outside this
  skill's scope).

## Quick start

### 1. Install `mlx-vlm` ≥ 0.7.1

```bash
# In your Hermes virtualenv (the one `hermes` runs in)
pip install --upgrade "mlx-vlm>=0.7.1" "mlx-audio"
```

Verify:

```bash
python3 -c "import mlx_vlm; print(mlx_vlm.__version__)"
# Expected: 0.7.1 or newer
```

### 2. Start the `mlx-vlm` server with a Parakeet model

```bash
# From the Hermes virtualenv (so the server picks up the right torch / mlx versions)
mlx_vlm serve --model mlx-community/parakeet-tdt-0.6b-v3 --port 8080
# Wait for "Application startup complete"
```

The first launch downloads the model from Hugging Face (≈ 700 MB for 4-bit). If
you're behind a DNS-poisoned network, configure a mirror first — see
[`references/troubleshooting.md`](references/troubleshooting.md#hf-mirror).

### 3. Tell Hermes to use the local server

Edit `~/.hermes/config.yaml`:

```yaml
stt:
  provider: openai
  openai:
    base_url: http://localhost:8080/v1
    api_key: not-needed               # mlx-vlm does not enforce an API key
    model: mlx-community/parakeet-tdt-0.6b-v3
```

The `openai` provider is **already built into Hermes** (`tools/transcription_tools.py`).
This skill doesn't add a new provider — it configures the existing one to point at a
local server that speaks the same wire protocol.

### 4. Verify

```bash
# Quick CLI smoke test
curl -X POST "http://localhost:8080/v1/audio/transcriptions" \
  -F "model=mlx-community/parakeet-tdt-0.6b-v3" \
  -F "file=@/path/to/your/voice-memo.mp3" \
  -F "response_format=json"

# Then in Hermes
hermes  # start a voice session; send a voice message
```

Expected response (with timestamps as of `mlx-vlm` 0.7.1):

```json
{
  "text": "你好,这是一段测试。",
  "segments": [
    {"id": 0, "start": 0.0, "end": 1.4, "text": "你好,"},
    {"id": 1, "start": 1.4, "end": 2.9, "text": "这是一段测试。"}
  ]
}
```

The `segments` field is what makes `mlx-vlm` 0.7.1 different from 0.7.0 — it now
emits OpenAI-conformant `segments` so SRT/VTT export "just works".

## Supported models

| Model | Size (4-bit) | Languages | Notes |
|---|---|---|---|
| `mlx-community/parakeet-tdt-0.6b-v3` | ~700 MB | EN, ES, FR, DE, IT, PT, plus 5 more | **Best accuracy/speed tradeoff** |
| `mlx-community/canary-1b-v2` | ~1.3 GB | EN, ES, FR, DE + translation to EN | Translation task via `/v1/audio/translations` |
| `mlx-community/parakeet-tdt-0.6b-v2` | ~700 MB | EN only | Older, slightly faster |

Browse all NeMo STT ports on Hugging Face: search
[`nemo`](https://huggingface.co/models?library=nemo&pipeline_tag=automatic-speech-recognition&sort=downloads)
filter on `mlx-community`.

## Why not just use `local` (faster-whisper)?

| Aspect | `faster-whisper` (Hermes built-in `local`) | `mlx-vlm` Parakeet (this skill) |
|---|---|---|
| First-run setup | `pip install faster-whisper` (~100 MB) | `pip install mlx-vlm>=0.7.1` + model download (~700 MB) |
| Apple Silicon speed | fast (int8) | very fast (Metal-native) |
| Multilingual accuracy (zh / ja / ko) | good (medium+) | **stronger** (Parakeet-TDT trained on broader multilingual set) |
| Word-level timestamps | yes | yes (via `segments` since 0.7.1) |
| Hallucination on silence | needs VAD on by default | rare (NeMo ASR models are well-behaved on silence) |
| Customisation | fine-tuning requires CTranslate2 | Hugging Face transformers |

If `faster-whisper medium` works for your language, stay on it. This skill is for the
cases where you specifically need better multilingual accuracy on Apple Silicon.

## Troubleshooting

See [`references/troubleshooting.md`](references/troubleshooting.md) for the full
list. The three most common gotchas:

1. **`mlx_vlm serve: command not found`** — your shell isn't using the Hermes venv.
   Activate it (`source ~/.hermes/hermes-agent/venv/bin/activate`) before running
   `mlx_vlm serve`.
2. **`HTTPConnectionPool(... localhost:8080): Connection refused`** — the server
   isn't running yet, or it's bound to a different port. Check the `mlx_vlm serve`
   output for the actual port.
3. **Transcription comes back as `{"text": ""}`** — usually a sample-rate mismatch.
   Parakeet expects 16 kHz mono PCM; some recorders produce 44.1 kHz stereo. Re-encode
   with `ffmpeg -i in.m4a -ac 1 -ar 16000 out.wav` before sending.

## Out of scope (deferred to other surfaces)

- **Realtime streaming** — `mlx-vlm` exposes `/v1/realtime` (WebSocket); Hermes does
  not yet consume it. Use a standalone Python client until that lands.
- **Translation** — `mlx-vlm` exposes `/v1/audio/translations`; Hermes's `openai`
  STT provider only hits `/v1/audio/transcriptions`. Use a CLI script for translation.
- **Custom fine-tunes** — load any `mlx-community/parakeet-*` variant by changing
  the `model:` field. No skill changes needed.

## Changelog

- 1.0.0 (2026-09-18) — Initial release. Tested against `mlx-vlm==0.7.1` (released
  2026-09-14). Parakeet-TDT-0.6B-v3 path validated end-to-end against the Hermes
  `openai` STT provider.
