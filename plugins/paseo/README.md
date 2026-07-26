# Paseo Bridge Plugin

Bridge Hermes Agent to [Paseo](https://github.com/getpaseo/paseo) — a multi-agent orchestrator for coding agents (Claude Code, Codex, Copilot, OpenCode, Pi).

## What it does

When the Paseo daemon is running locally, this plugin exposes Hermes tools that let the agent:

- **Discover** which external coding agents are installed (`paseo_list_providers`)
- **Spawn** new agents on Paseo with specific providers/models (`paseo_create_agent`)
- **Send follow-ups** to running agents (`paseo_send_prompt`)
- **Monitor** active agents and workspaces (`paseo_list_agents`, `paseo_list_workspaces`)
- **Create isolated workspaces** for delegation (`paseo_create_workspace`)

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Hermes Agent (Python)                          │
│  ┌──────────────┐    ┌───────────────────────┐  │
│  │ Core Agent   │───>│ paseo_bridge plugin   │  │
│  │ + Skills     │    │ (WebSocket client)    │  │
│  └──────────────┘    └──────────┬────────────┘  │
└─────────────────────────────────┼───────────────┘
                                  │ WebSocket
                                  ▼
┌─────────────────────────────────────────────────┐
│  Paseo Daemon (TypeScript, localhost:6767)      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ Claude   │  │ Codex    │  │ Copilot/      │  │
│  │ Code     │  │          │  │ OpenCode      │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│  Workspace + Worktree Management                 │
│  Agent Lifecycle + Scheduling                    │
└─────────────────────────────────────────────────┘
```

## Configuration

Set these environment variables or `config.yaml` keys:

```yaml
# config.yaml
plugins:
  entries:
    paseo-bridge:
      enabled: true
```

```bash
# Environment variables (optional, defaults shown)
export PASEO_LISTEN="127.0.0.1:6767"   # daemon address
export PASEO_PASSWORD=""                # auth (if configured)
export PASEO_TLS="false"                # TLS toggle
```

## Tools

| Tool | Description |
|------|-------------|
| `paseo_list_providers` | List available agent providers |
| `paseo_list_models` | List models for a provider |
| `paseo_create_agent` | Create a new agent on Paseo |
| `paseo_send_prompt` | Send follow-up to an agent |
| `paseo_list_agents` | List active agents |
| `paseo_list_workspaces` | List active workspaces |
| `paseo_create_workspace` | Create workspace (local or worktree) |

## Dependencies

- `websockets` Python package (for WebSocket communication)
- Paseo daemon running locally
- At least one coding agent installed (Claude Code, Codex, etc.)

## Why this matters for Hermes

Hermes already has `delegate_task` for internal subagents. The Paseo bridge adds:

1. **External agent orchestration** — Run Claude Code/Codex as independent agents with their own toolsets, permissions, and environments
2. **Workspace isolation** — Create git worktrees for isolated agent work
3. **Provider diversity** — Use contrasting providers (Opus vs GPT-5.4) for committee-style analysis
4. **Persistent agents** — Paseo agents survive Hermes restarts, with state stored in `~/.paseo/`

Combined with Hermes skills (`paseo-advisor`, `paseo-committee`, `paseo-handoff`, `paseo-loop`), this creates a powerful multi-agent workflow where Hermes coordinates and Paseo executes.
