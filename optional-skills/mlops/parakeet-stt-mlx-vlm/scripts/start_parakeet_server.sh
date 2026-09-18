#!/usr/bin/env bash
# Start the mlx-vlm server with a Parakeet STT model.
#
# Usage:
#   scripts/start_parakeet_server.sh [model] [port]
#
# Defaults:
#   model = mlx-community/parakeet-tdt-0.6b-v3  (best accuracy/speed tradeoff)
#   port  = 8080
#
# Environment overrides:
#   PARAKEET_MODEL  – model ID (any mlx-community/* parakeet or canary variant)
#   PARAKEET_PORT   – port to bind (default 8080)
#
# The server speaks the OpenAI-compatible /v1/audio/transcriptions endpoint so
# Hermes's built-in `openai` STT provider can consume it directly (no Hermes
# changes required).

set -euo pipefail

MODEL="${1:-${PARAKEET_MODEL:-mlx-community/parakeet-tdt-0.6b-v3}}"
PORT="${2:-${PARAKEET_PORT:-8080}}"

echo "▶ Starting mlx-vlm server with model: $MODEL on port $PORT"
echo "  (first launch downloads the model from Hugging Face — be patient)"
echo "  ctrl-c to stop."
echo

exec mlx_vlm serve --model "$MODEL" --port "$PORT"
