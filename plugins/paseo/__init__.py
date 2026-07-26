"""paseo-bridge plugin — connect to Paseo daemon for multi-agent orchestration.

Exposes Hermes tools that delegate work to external coding agents
(Claude Code, Codex, Copilot, OpenCode) via Paseo's daemon API.

Paseo daemon defaults to localhost:6767 (override PASEO_LISTEN).
The bridge communicates over WebSocket using Paseo's binary protocol.

Tools registered:
- paseo_list_providers   — discover available agent providers
- paseo_list_models      — list models for a provider
- paseo_create_agent     — spawn a new agent on Paseo daemon
- paseo_send_prompt      — send follow-up prompt to an existing agent
- paseo_list_agents      — list active/archived agents
- paseo_list_workspaces  — list active workspaces
- paseo_create_workspace — create a workspace (local or worktree isolation)

Usage:
    from plugins.paseo import PaseoBridge
    bridge = PaseoBridge(dameon_url="ws://localhost:6767/ws")
    providers = await bridge.list_providers()
    agent = await bridge.create_agent(title="Fix bug", provider="claude/sonnet", prompt="...")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WebSocket client for Paseo daemon
# ---------------------------------------------------------------------------

_PASEO_WS_PROTO = "paseo.bearer."

@dataclass
class PaseoDaemonConfig:
    """Configuration for connecting to a Paseo daemon."""
    host: str = "127.0.0.1"
    port: int = 6767
    password: Optional[str] = None
    use_tls: bool = False

    @property
    def ws_url(self) -> str:
        scheme = "wss" if self.use_tls else "ws"
        return f"{scheme}://{self.host}:{self.port}/ws"

    @classmethod
    def from_env(cls) -> "PaseoDaemonConfig":
        listen = os.environ.get("PASEO_LISTEN", "127.0.0.1:6767")
        host, _, port_str = listen.rpartition(":")
        if not host:
            host = "127.0.0.1"
        port = int(port_str) if port_str.isdigit() else 6767
        password = os.environ.get("PASEO_PASSWORD")
        use_tls = os.environ.get("PASEO_TLS", "false").lower() == "true"
        return cls(host=host, port=port, password=password, use_tls=use_tls)


@dataclass
class PaseoAgent:
    """Descriptor for an agent on the Paseo daemon."""
    agent_id: str
    title: str
    provider: str
    workspace_id: str
    status: str  # "idle", "running", "error", "closed"
    created_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PaseoWorkspace:
    """Descriptor for a workspace on the Paseo daemon."""
    workspace_id: str
    path: str
    isolation: str  # "local" or "worktree"
    branch: Optional[str] = None


@dataclass
class PaseoProvider:
    """Descriptor for an agent provider."""
    id: str
    label: str
    description: str
    default_mode_id: Optional[str] = None
    modes: List[Dict[str, str]] = field(default_factory=list)
    available: bool = True


class PaseoBridge:
    """Bridge to Paseo daemon for multi-agent orchestration.

    Uses WebSocket to communicate with the Paseo daemon, sending
    JSON-RPC style messages over the binary protocol.
    """

    def __init__(self, config: Optional[PaseoDaemonConfig] = None):
        self._config = config or PaseoDaemonConfig.from_env()
        self._ws = None
        self._message_id = 0

    @property
    def config(self) -> PaseoDaemonConfig:
        return self._config

    async def _ensure_connection(self):
        """Lazy-connect to the Paseo daemon."""
        if self._ws is not None:
            return
        try:
            import websockets
            ws_url = self._config.ws_url
            headers = {}
            if self._config.password:
                headers["Sec-WebSocket-Protocol"] = f"{_PASEO_WS_PROTO}{self._config.password}"
            self._ws = await asyncio.wait_for(
                websockets.connect(ws_url, additional_headers=headers),
                timeout=10,
            )
            logger.info("Connected to Paseo daemon at %s", ws_url)
        except ImportError:
            raise RuntimeError(
                "websockets package required for Paseo bridge. "
                "Install with: pip install websockets"
            )
        except (ConnectionRefusedError, OSError) as e:
            raise ConnectionError(
                f"Cannot connect to Paseo daemon at {self._config.ws_url}: {e}. "
                "Ensure Paseo daemon is running (paseo daemon start)."
            ) from e

    async def _send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send a JSON-RPC request and await the response."""
        await self._ensure_connection()
        assert self._ws is not None, "WebSocket not connected"
        self._message_id += 1
        msg_id = self._message_id
        request = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params or {},
        }
        await self._ws.send(json.dumps(request))
        while True:
            response = await asyncio.wait_for(self._ws.recv(), timeout=30)
            if isinstance(response, bytes):
                # Binary frame — parse header to find JSON payload
                try:
                    data = json.loads(response.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Binary protocol: skip non-JSON frames
                    continue
            else:
                data = json.loads(response)
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"Paseo daemon error: {data['error']}")
                return data.get("result")

    async def close(self):
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None

    # -----------------------------------------------------------------------
    # Tool implementations
    # -----------------------------------------------------------------------

    async def list_providers(self) -> List[Dict[str, Any]]:
        """List available agent providers on the Paseo daemon."""
        result = await self._send_request("list_providers")
        providers = []
        for p in (result or []):
            providers.append({
                "id": p.get("id", ""),
                "label": p.get("label", ""),
                "description": p.get("description", ""),
                "available": p.get("available", True),
                "modes": [
                    {"id": m.get("id"), "label": m.get("label")}
                    for m in p.get("modes", [])
                ],
            })
        return providers

    async def list_models(self, provider: str) -> List[Dict[str, Any]]:
        """List available models for a specific provider."""
        result = await self._send_request("list_models", {"provider": provider})
        return result or []

    async def create_agent(
        self,
        title: str,
        provider: str,
        initial_prompt: str,
        workspace_id: Optional[str] = None,
        mode_id: Optional[str] = None,
        notify_on_finish: bool = True,
        labels: Optional[List[str]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new agent on the Paseo daemon."""
        params: Dict[str, Any] = {
            "title": title,
            "provider": provider,
            "initialPrompt": initial_prompt,
            "notifyOnFinish": notify_on_finish,
        }
        if workspace_id:
            params["workspaceId"] = workspace_id
        if mode_id:
            params.setdefault("settings", {})["modeId"] = mode_id
        if settings:
            params.setdefault("settings", {}).update(settings)
        if labels:
            params["labels"] = labels

        result = await self._send_request("create_agent", params)
        return {
            "agent_id": result.get("agentId", ""),
            "workspace_id": result.get("workspaceId", ""),
            "title": result.get("title", title),
            "provider": result.get("provider", provider),
        }

    async def send_prompt(
        self,
        agent_id: str,
        prompt: str,
        background: bool = True,
    ) -> Dict[str, Any]:
        """Send a follow-up prompt to an existing agent."""
        params = {
            "agentId": agent_id,
            "prompt": prompt,
            "background": background,
        }
        result = await self._send_request("send_agent_prompt", params)
        return {
            "agent_id": agent_id,
            "success": result.get("success", True),
            "message": result.get("message", "Prompt sent"),
        }

    async def list_agents(
        self,
        statuses: Optional[List[str]] = None,
        since_hours: int = 24,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """List active agents on the Paseo daemon."""
        params: Dict[str, Any] = {
            "sinceHours": since_hours,
            "includeArchived": include_archived,
        }
        if statuses:
            params["statuses"] = statuses

        result = await self._send_request("list_agents", params)
        agents = []
        for a in (result or []):
            agents.append({
                "agent_id": a.get("agentId", ""),
                "title": a.get("title", ""),
                "provider": a.get("provider", ""),
                "status": a.get("status", "unknown"),
                "workspace_id": a.get("workspaceId", ""),
            })
        return agents

    async def list_workspaces(self) -> List[Dict[str, Any]]:
        """List active workspaces."""
        result = await self._send_request("list_workspaces")
        workspaces = []
        for w in (result or []):
            workspaces.append({
                "workspace_id": w.get("workspaceId", ""),
                "path": w.get("path", ""),
                "isolation": w.get("isolation", "local"),
            })
        return workspaces

    async def create_workspace(
        self,
        isolation: str = "local",
        worktree_mode: Optional[str] = None,
        branch_name: Optional[str] = None,
        base_branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new workspace."""
        params: Dict[str, Any] = {"isolation": isolation}
        if isolation == "worktree":
            wt = {}
            if worktree_mode:
                wt["mode"] = worktree_mode
            if branch_name:
                wt["branchName"] = branch_name
            if base_branch:
                wt["baseBranch"] = base_branch
            if wt:
                params["worktree"] = wt

        result = await self._send_request("create_workspace", params)
        return {
            "workspace_id": result.get("workspaceId", ""),
            "path": result.get("path", ""),
            "isolation": result.get("isolation", isolation),
        }


# ---------------------------------------------------------------------------
# Hermes plugin registration
# ---------------------------------------------------------------------------

def register(ctx):
    """Register Paseo bridge tools with Hermes."""
    bridge = None

    def _get_bridge():
        nonlocal bridge
        if bridge is None:
            bridge = PaseoBridge()
        return bridge

    @ctx.register_tool("paseo_list_providers")
    async def paseo_list_providers():
        """List available agent providers on the Paseo daemon.

        Returns provider IDs, labels, descriptions, and available modes.
        Use this to discover what external agents (Claude Code, Codex, etc.)
        are installed and available before creating agents.
        """
        try:
            providers = await _get_bridge().list_providers()
            if not providers:
                return {"providers": [], "note": "No providers available. Ensure Paseo daemon is running and agents are installed."}
            return {"providers": providers}
        except ConnectionError as e:
            return {"error": str(e), "hint": "Start Paseo daemon: paseo daemon start"}
        except Exception as e:
            return {"error": f"Failed to list providers: {e}"}

    @ctx.register_tool("paseo_list_models")
    async def paseo_list_models(provider: str):
        """List available models for a Paseo provider.

        Args:
            provider: Provider ID (e.g. "claude", "codex").
        """
        try:
            models = await _get_bridge().list_models(provider)
            return {"provider": provider, "models": models}
        except Exception as e:
            return {"error": f"Failed to list models for {provider}: {e}"}

    @ctx.register_tool("paseo_create_agent")
    async def paseo_create_agent(
        title: str,
        provider: str,
        initial_prompt: str,
        workspace_id: Optional[str] = None,
        mode_id: Optional[str] = None,
        notify_on_finish: bool = True,
        labels: Optional[list] = None,
    ):
        """Create a new external agent via Paseo daemon.

        Spawns an external coding agent (Claude Code, Codex, etc.) on the
        Paseo daemon. The agent runs independently and notifies on finish.

        Args:
            title: Agent title for tracking.
            provider: Provider ID (from paseo_list_providers).
            initial_prompt: Task description for the agent.
            workspace_id: Optional workspace to run in.
            mode_id: Optional provider mode (e.g. "auto", "full-access").
            notify_on_finish: Whether to notify when agent completes.
            labels: Optional labels for the agent.
        """
        try:
            result = await _get_bridge().create_agent(
                title=title,
                provider=provider,
                initial_prompt=initial_prompt,
                workspace_id=workspace_id,
                mode_id=mode_id,
                notify_on_finish=notify_on_finish,
                labels=labels,
            )
            return {
                "agent_id": result["agent_id"],
                "workspace_id": result["workspace_id"],
                "title": result["title"],
                "provider": result["provider"],
                "status": "created",
            }
        except Exception as e:
            return {"error": f"Failed to create agent: {e}"}

    @ctx.register_tool("paseo_send_prompt")
    async def paseo_send_prompt(agent_id: str, prompt: str, background: bool = True):
        """Send a follow-up prompt to an existing Paseo agent.

        Args:
            agent_id: The agent to send the prompt to.
            prompt: The follow-up instruction.
            background: Whether to run asynchronously (default: True).
        """
        try:
            result = await _get_bridge().send_prompt(agent_id, prompt, background)
            return result
        except Exception as e:
            return {"error": f"Failed to send prompt: {e}"}

    @ctx.register_tool("paseo_list_agents")
    async def paseo_list_agents(
        statuses: Optional[list] = None,
        since_hours: int = 24,
        include_archived: bool = False,
    ):
        """List active agents on the Paseo daemon.

        Args:
            statuses: Filter by status list (idle, running, error, closed).
            since_hours: Only show agents from the last N hours.
            include_archived: Include archived agents.
        """
        try:
            agents = await _get_bridge().list_agents(
                statuses=statuses,
                since_hours=since_hours,
                include_archived=include_archived,
            )
            return {"agents": agents, "count": len(agents)}
        except Exception as e:
            return {"error": f"Failed to list agents: {e}"}

    @ctx.register_tool("paseo_list_workspaces")
    async def paseo_list_workspaces():
        """List active workspaces on the Paseo daemon."""
        try:
            workspaces = await _get_bridge().list_workspaces()
            return {"workspaces": workspaces, "count": len(workspaces)}
        except Exception as e:
            return {"error": f"Failed to list workspaces: {e}"}

    @ctx.register_tool("paseo_create_workspace")
    async def paseo_create_workspace(
        isolation: str = "local",
        worktree_mode: Optional[str] = None,
        branch_name: Optional[str] = None,
        base_branch: Optional[str] = None,
    ):
        """Create a new workspace on the Paseo daemon.

        Args:
            isolation: "local" or "worktree".
            worktree_mode: For worktree isolation: "branch-off", "checkout-branch", or "checkout-pr".
            branch_name: New branch name (for branch-off mode).
            base_branch: Base branch (for branch-off mode).
        """
        try:
            result = await _get_bridge().create_workspace(
                isolation=isolation,
                worktree_mode=worktree_mode,
                branch_name=branch_name,
                base_branch=base_branch,
            )
            return result
        except Exception as e:
            return {"error": f"Failed to create workspace: {e}"}
