"""Ollama model puller with streaming progress feedback."""

from __future__ import annotations

import logging
from typing import Callable, Optional

import httpx

logger = logging.getLogger(__name__)


def pull_model(
    model_name: str,
    host: str = "http://localhost:11434",
    timeout: int = 300,
    status_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """Pull an Ollama model with streaming progress feedback.

    Sends a ``POST /api/pull`` with ``{"name": model_name, "stream": true}``
    and parses the NDJSON response lines for status updates.  The
    ``status_callback`` is invoked with human-readable progress messages
    (throttled to ~every 2 seconds to avoid flooding).

    Returns ``True`` if the model was pulled successfully.
    """
    try:
        if status_callback:
            status_callback(f"⏳ Pulling model {model_name}...")

        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            with client.stream(
                "POST",
                f"{host}/api/pull",
                json={"name": model_name, "stream": True},
            ) as response:
                if response.status_code != 200:
                    logger.error(
                        "Failed to pull model %s: HTTP %s",
                        model_name, response.status_code,
                    )
                    if status_callback:
                        status_callback(
                            f"❌ Failed to pull {model_name} "
                            f"(HTTP {response.status_code})"
                        )
                    return False

                _last_progress = 0.0
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        import json
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    status = data.get("status", "")
                    if status == "success":
                        if status_callback:
                            status_callback(
                                f"✅ Model {model_name} pulled successfully"
                            )
                        return True

                    # Throttle progress updates to ~every 2s
                    now = _now_seconds()
                    if status_callback and (now - _last_progress) >= 2.0:
                        _last_progress = now
                        total = data.get("total", 0) or 0
                        completed = data.get("completed", 0) or 0
                        pct = (
                            f"{completed // (1024 * 1024)}MB / "
                            f"{total // (1024 * 1024)}MB"
                        ) if total else status
                        status_callback(f"⏳ {model_name}: {pct}")

                logger.error(
                    "Model pull stream ended without success for %s",
                    model_name,
                )
                if status_callback:
                    status_callback(f"❌ Pull stream ended unexpectedly for {model_name}")
                return False

    except Exception as exc:
        logger.error("Failed to pull model %s: %s", model_name, exc)
        if status_callback:
            status_callback(f"❌ Error pulling {model_name}: {exc}")
        return False


def _now_seconds() -> float:
    """Return monotonic time in seconds (Python 3.7+ compat)."""
    import time
    return time.monotonic()
