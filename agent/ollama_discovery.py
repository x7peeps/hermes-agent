"""Ollama binary and server discovery utilities."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

_OLLAMA_COMMON_PATHS = [
    "/usr/local/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/home/linuxbrew/.linuxbrew/bin/ollama",
    "/snap/bin/ollama",
]


def find_ollama_binary() -> Optional[str]:
    """Find the ollama binary on the system.

    Checks PATH first, then common install locations.
    Returns the full path to the binary, or ``None`` if not found.
    """
    path = shutil.which("ollama")
    if path:
        return path
    for candidate in _OLLAMA_COMMON_PATHS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def check_ollama_health(host: str = "http://localhost:11434", timeout: int = 3) -> bool:
    """Check if the Ollama server is running and healthy.

    Sends a ``GET /api/tags`` request to the Ollama API.
    Returns ``True`` if the server responds with HTTP 200.
    """
    try:
        import httpx
        resp = httpx.get(f"{host}/api/tags", timeout=timeout)
        return resp.status_code == 200
    except Exception as exc:
        logger.debug("Ollama health check failed: %s", exc)
        return False


def start_ollama_serve(binary_path: str, timeout: int = 10) -> bool:
    """Start the Ollama server in the background.

    Runs ``{binary_path} serve`` as a background process, then polls
    the health endpoint until the server responds or ``timeout`` seconds
    elapse.

    Returns ``True`` if the server is running within the timeout.
    """
    try:
        subprocess.Popen(
            [binary_path, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check_ollama_health():
                logger.info("Ollama server started successfully")
                return True
            time.sleep(0.5)
        logger.warning("Ollama server did not start within %ds", timeout)
        return False
    except Exception as exc:
        logger.error("Failed to start Ollama server: %s", exc)
        return False


def list_available_models(host: str = "http://localhost:11434") -> List[str]:
    """List models available in the local Ollama instance.

    Returns a list of model name strings, or an empty list if the
    server is unreachable or has no models.
    """
    try:
        import httpx
        resp = httpx.get(f"{host}/api/tags", timeout=5)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception as exc:
        logger.debug("Failed to list Ollama models: %s", exc)
        return []


def install_ollama() -> bool:
    """Attempt to install Ollama via the system package manager.

    macOS: ``brew install ollama``
    Linux (apt): not implemented yet (auto-install is non-trivial)

    Returns ``True`` if installation succeeded.
    """
    try:
        import platform as _platform
        system = _platform.system().lower()
        if system == "darwin":
            result = subprocess.run(
                ["brew", "install", "ollama"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0:
                logger.info("Ollama installed successfully via Homebrew")
                return True
            logger.warning("Homebrew install failed: %s", result.stderr)
            return False
        else:
            logger.info("Auto-install not yet supported on %s", system)
            return False
    except Exception as exc:
        logger.error("Failed to install Ollama: %s", exc)
        return False
