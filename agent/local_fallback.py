"""Local Ollama fallback orchestrator.

When all remote providers and configured fallbacks are exhausted, this
module attempts to find or set up a local Ollama model to keep the
conversation going.

The process:
  1. Check local_fallback.enabled config
  2. Find the ollama binary on the system
  3. Check server health (start if needed)
  4. List available models (pull the configured default if empty)
  5. Switch the agent's active provider to Ollama
  6. On the next turn, attempt to restore the primary provider
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


def local_fallback_orchestrator(agent: Any) -> Tuple[bool, str]:
    """Orchestrate the full local fallback process.

    Returns ``(True, model_name)`` on success, ``(False, error_message)``
    on failure.

    The agent object is modified in-place: ``agent.model``, ``agent.provider``,
    ``agent.base_url``, and ``agent.client`` are updated to point to the local
    Ollama instance.
    """
    # Step 1: Check config
    fb_config = getattr(agent, "_local_fallback_config", {})
    if not fb_config.get("enabled", False):
        return False, "Local fallback is not enabled in config"

    model = fb_config.get("model", "qwen3.5:0.8b")
    host = fb_config.get("ollama_host", "http://localhost:11434")
    ask_user = fb_config.get("ask_user", True)
    auto_pull = fb_config.get("auto_pull", True)
    auto_install = fb_config.get("auto_install", False)
    serve_timeout = int(fb_config.get("serve_timeout", 10))
    download_timeout = int(fb_config.get("download_timeout", 300))

    # Step 2: Find ollama binary
    from agent.ollama_discovery import (
        check_ollama_health,
        find_ollama_binary,
        install_ollama,
        list_available_models,
        start_ollama_serve,
    )

    binary = find_ollama_binary()
    if binary is None:
        if auto_install:
            agent._buffer_status("📦 Ollama not found — installing...")
            if not install_ollama():
                return False, "Failed to install Ollama automatically"
            binary = find_ollama_binary()
            if binary is None:
                return False, "Ollama installed but binary not found"
        else:
            agent._buffer_status(
                "💡 Ollama not found. Set local_fallback.auto_install=true "
                "to auto-install, or install manually: brew install ollama"
            )
            return False, "Ollama not installed"

    # Step 3: Check / start server
    if not check_ollama_health(host=host):
        agent._buffer_status("🚀 Starting Ollama server...")
        if not start_ollama_serve(binary, timeout=serve_timeout):
            return False, "Failed to start Ollama server"

    # Step 4: List available models, pull if needed
    available = list_available_models(host=host)
    if not available:
        if auto_pull:
            agent._buffer_status(f"📥 No models found — pulling {model}...")
            from agent.model_puller import pull_model
            if not pull_model(
                model, host=host, timeout=download_timeout,
                status_callback=lambda msg: agent._buffer_status(msg),
            ):
                return False, f"Failed to pull model {model}"
            available = list_available_models(host=host)

        if not available:
            return False, (
                f"No models available and auto-pull is disabled. "
                f"Run: ollama pull {model}"
            )

    # Pick the smallest available model (or the configured one)
    target_model = model
    if target_model not in available:
        # Fall back to first available
        target_model = available[0]

    # Step 5: Switch agent to Ollama
    _switch_agent_to_ollama(agent, target_model, host)
    agent._buffer_status(
        f"🔄 Switched to local model: {target_model} (Ollama)"
    )

    return True, target_model


def restore_primary_provider(agent: Any) -> bool:
    """Attempt to restore the original primary provider.

    Checks whether the primary provider's config is still viable.  If so,
    restores the agent state from ``agent._primary_runtime`` and returns
    ``True``.

    Called on every conversation turn when local fallback is active.
    """
    if not getattr(agent, "_on_local_fallback", False):
        return False

    # Check if primary runtime snapshot exists
    primary = getattr(agent, "_primary_runtime", None)
    if not primary:
        return False

    # Quick health check — try a simple models list to see if primary is back
    try:
        base_url = primary.get("base_url", "")
        api_key = primary.get("api_key", "")
        if base_url and api_key:
            resp = httpx.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=5,
            )
            if resp.status_code == 200:
                _perform_restore(agent, primary)
                return True
    except Exception:
        pass

    return False


def _switch_agent_to_ollama(agent: Any, model_name: str, host: str) -> None:
    """Reconfigure the agent's active provider to Ollama.

    Sets ``agent.model``, ``agent.provider``, ``agent.base_url``,
    ``agent._client_kwargs``, and rebuilds the OpenAI client via
    ``agent._create_openai_client()``.
    """
    agent.model = model_name
    agent.provider = "ollama"
    agent.base_url = host
    agent._client_kwargs = {"base_url": host}
    agent._on_local_fallback = True

    try:
        agent.client = agent._create_openai_client(
            agent._client_kwargs,
            reason="local_fallback",
        )
        logger.info(
            "Switched to local Ollama model: %s (host=%s)",
            model_name, host,
        )
    except Exception as exc:
        logger.error("Failed to create Ollama client: %s", exc)
        raise


def _perform_restore(agent: Any, primary: Dict[str, Any]) -> None:
    """Restore agent state from a primary runtime snapshot."""
    agent.model = primary.get("model", agent.model)
    agent.provider = primary.get("provider", agent.provider)
    agent.base_url = primary.get("base_url", agent.base_url)
    agent.api_mode = primary.get("api_mode", agent.api_mode)
    agent.api_key = primary.get("api_key", agent.api_key)
    agent._client_kwargs = dict(primary.get("client_kwargs", {}))
    agent._on_local_fallback = False

    try:
        agent.client = agent._create_openai_client(
            agent._client_kwargs,
            reason="restore_primary",
        )
        logger.info("Restored primary provider: %s (%s)", agent.model, agent.provider)
    except Exception as exc:
        logger.error("Failed to restore primary client: %s", exc)
