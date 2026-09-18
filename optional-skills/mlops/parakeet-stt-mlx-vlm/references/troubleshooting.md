# Troubleshooting Parakeet STT via `mlx-vlm` server

Common failure modes and how to diagnose them. Start at the top and work down —
each section assumes the previous ones have been verified.

## 1. `mlx_vlm: command not found`

**Cause**: your shell isn't using the Hermes virtualenv.

**Fix**: activate the venv before running the server.

```bash
source ~/.hermes/hermes-agent/venv/bin/activate
mlx_vlm serve --model mlx-community/parakeet-tdt-0.6b-v3 --port 8080
```

To make this permanent for your shell session, add the activate line to your
`~/.zshrc` / `~/.bashrc`.

## 2. HF download fails / hangs forever (`ConnectTimeout` on `huggingface.co`)

**Cause**: `huggingface.co` is DNS-poisoned in your region, or your firewall blocks it.

**Fix**: point `huggingface_hub` at a mirror. This is now part of Hermes's STT
config thanks to PR #125 — the same `HF_ENDPOINT` env var works here:

```bash
export HF_ENDPOINT=https://hf-mirror.com
mlx_vlm serve --model mlx-community/parakeet-tdt-0.6b-v3 --port 8080
```

If you're using a mirror that serves `hf-xet` payloads, also export
`HF_HUB_DISABLE_XET=1` to avoid the empty-download bug.

## 3. Server starts, `curl /health` returns 200, but transcription returns `{"text": ""}`

**Cause**: sample-rate / channel mismatch. Parakeet was trained on 16 kHz mono
PCM. Anything else (44.1 kHz, stereo) decodes as silence.

**Fix**: re-encode the audio before sending:

```bash
ffmpeg -i input.m4a -ac 1 -ar 16000 -c:a pcm_s16le input_16k.wav
```

Then send `input_16k.wav` instead.

You can verify the WAV is correct with:

```bash
ffprobe input_16k.wav  # should show "1 channels, 16000 Hz"
```

## 4. `out of memory` after a few minutes of use

**Cause**: `mlx-vlm` keeps models cached in unified memory between requests. On
8 GB hosts, a Canary-1B model can OOM under sustained load.

**Fix**: use the smaller Parakeet-TDT-0.6B-v3 (≈ 700 MB in 4-bit), or call
`POST /unload` between heavy batches to free the cache:

```bash
curl -X POST http://localhost:8080/unload
```

For very long-running production setups, restart the server every N hours via
cron.

## 5. Transcription is slow (multiple seconds for a 10-second clip)

**Cause**: the first transcription after a model load pays the cold-start cost
(weight load + Metal kernel compile). Subsequent calls should be sub-second.

**Fix**: send a "warm-up" request right after the server starts:

```bash
curl -X POST http://localhost:8080/v1/audio/transcriptions \
    -F "model=mlx-community/parakeet-tdt-0.6b-v3" \
    -F "file=@$(brew --prefix)/share/sounds/Liquid\ Subzero.aiff" \
    -F "response_format=json"
```

(That file ships with macOS and is a tiny known audio — perfect warm-up.)
After that, normal audio should respond in ~0.5–2 s.

## 6. Hermes doesn't pick up the local server

**Cause**: `stt.openai.base_url` isn't pointed at the server, or Hermes's
`provider` is still set to `local`.

**Fix**: verify the config block in `~/.hermes/config.yaml`:

```yaml
stt:
  provider: openai            # not "local"!
  openai:
    base_url: http://localhost:8080/v1
    api_key: not-needed
    model: mlx-community/parakeet-tdt-0.6b-v3
```

Run `hermes config show stt` to confirm what Hermes sees.

## 7. Audio input is fine but segments have no timestamps

**Cause**: you're on `mlx-vlm < 0.7.1`. Word-level `segments` (and the resulting
SRT/VTT export) were added in 0.7.1 by PR Blaizzy/mlx-vlm#2189.

**Fix**: upgrade — see `scripts/install_deps.sh`.
