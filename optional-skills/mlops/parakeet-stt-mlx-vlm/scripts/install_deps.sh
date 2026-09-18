#!/usr/bin/env bash
# Install the Python dependencies this skill needs into the active virtualenv.
#
# Usage:
#   scripts/install_deps.sh
#
# Idempotent: safe to re-run. Uses pip's --upgrade-strategy only-if-needed to
# avoid touching unrelated packages. Pins mlx-vlm to >=0.7.1 because the
# OpenAI-conformant /v1/audio/transcriptions endpoint was added in that release
# (PR Blaizzy/mlx-vlm#2189, "Return OpenAI segments for NeMo-alignment STT models").

set -euo pipefail

# Sanity-check: refuse to run outside a virtualenv so we never pollute the
# system Python on a fresh macOS box.
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "✗ This script must be run inside the Hermes virtualenv." >&2
    echo "  Activate it first:  source ~/.hermes/hermes-agent/venv/bin/activate" >&2
    exit 2
fi

echo "▶ Upgrading pip (idempotent)"
python3 -m pip install --quiet --upgrade pip

echo "▶ Installing mlx-vlm>=0.7.1 and mlx-audio"
python3 -m pip install --quiet --upgrade "mlx-vlm>=0.7.1" mlx-audio

echo "▶ Verifying install"
python3 - <<'PY'
import mlx_vlm
import sys
from packaging.version import Version

need = Version("0.7.1")
have = Version(mlx_vlm.__version__)
print(f"  mlx-vlm: {have}  (need >= {need})")
if have < need:
    print("  ✗ Installed mlx-vlm is older than the minimum required.", file=sys.stderr)
    sys.exit(1)
print("  ✓ OK")
PY

echo
echo "✓ Done. Next step:"
echo "    scripts/start_parakeet_server.sh"
