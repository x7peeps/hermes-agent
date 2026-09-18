#!/usr/bin/env bash
# Smoke-test the Parakeet STT server end-to-end without going through Hermes.
#
# Usage:
#   scripts/transcribe_cli.sh <audio-file> [model] [port]
#
# Defaults:
#   model = mlx-community/parakeet-tdt-0.6b-v3
#   port  = 8080
#
# Sends the file to the running server's /v1/audio/transcriptions endpoint and
# pretty-prints the JSON response. Returns the server's exit-1 if the response
# isn't valid JSON so the caller can detect a misconfigured server.

set -euo pipefail

AUDIO="${1:?Usage: $0 <audio-file> [model] [port]}"
MODEL="${2:-mlx-community/parakeet-tdt-0.6b-v3}"
PORT="${3:-8080}"

if [[ ! -f "$AUDIO" ]]; then
    echo "✗ audio file not found: $AUDIO" >&2
    exit 2
fi

# Pre-flight: is the server actually up?
if ! curl -fsS --max-time 2 "http://localhost:${PORT}/health" > /dev/null 2>&1; then
    echo "✗ server not reachable on http://localhost:${PORT}/health" >&2
    echo "  start it first:  scripts/start_parakeet_server.sh" >&2
    exit 3
fi

curl -fsS -X POST "http://localhost:${PORT}/v1/audio/transcriptions" \
    -F "model=${MODEL}" \
    -F "file=@${AUDIO}" \
    -F "response_format=json" \
| python3 -m json.tool
