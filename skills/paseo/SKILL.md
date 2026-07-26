---
name: paseo
description: Paseo reference for managing workspaces, agents, and multi-provider orchestration through the paseo-bridge plugin. Use when the user wants to delegate to external coding agents (Claude Code, Codex, Copilot, OpenCode) via Paseo daemon.
---

# Paseo Multi-Agent Orchestration

Paseo is a daemon that supervises AI coding agents on your machine. Through the **paseo-bridge plugin**, Hermes can connect to the Paseo daemon (default `localhost:6767`) and orchestrate external agents.

## When to use

- The user wants to run **Claude Code, Codex, Copilot, or OpenCode** as independent agents
- The task needs **workspace isolation** (git worktrees)
- The user wants **contrasting provider opinions** (advisor/committee patterns)
- Delegating to agents that need **different permission models** than Hermes provides

## Prerequisites

Before using any Paseo skill, check:

```
paseo_list_providers()
```

If this returns an error, the Paseo daemon is not running. Tell the user to install and start it:
```bash
# Install Paseo
# See https://github.com/getpaseo/paseo
paseo daemon start
```

## Orchestration Preferences

**Before choosing a provider or creating an agent, read** `~/.paseo/orchestration-preferences.json`:

```json
{
  "providers": {
    "impl": "codex/gpt-5.4",
    "ui": "claude/opus",
    "research": "codex/gpt-5.4",
    "planning": "codex/gpt-5.4",
    "audit": "codex/gpt-5.4"
  },
  "preferences": [
    "Claude Opus is the right choice for anything artistic or human-skill-oriented"
  ]
}
```

Categories: `impl`, `ui`, `research`, `planning`, `audit`. Pick the category matching the role. If the file is missing, use sensible defaults.

## Available Tools

| Tool | Purpose |
|------|---------|
| `paseo_list_providers` | Discover installed agent providers |
| `paseo_list_models` | List models for a provider |
| `paseo_create_agent` | Spawn a new agent |
| `paseo_send_prompt` | Follow-up prompt |
| `paseo_list_agents` | Monitor agents |
| `paseo_list_workspaces` | List workspaces |
| `paseo_create_workspace` | Create isolated workspace |

## Provider Reference

| Provider ID | Agent | Default Model |
|-------------|-------|---------------|
| `claude/sonnet` | Claude Code | Claude Sonnet |
| `claude/opus` | Claude Code | Claude Opus |
| `claude/haiku` | Claude Code | Claude Haiku |
| `codex/gpt-5.4` | Codex | GPT-5.4 |

## Agent Modes

Each provider has modes with different permission levels:

- **Claude**: `plan`, `default`, `acceptEdits`, `auto`, `bypassPermissions`
- **Codex**: `auto`, `auto-review`, `full-access`

`full-access` / `bypassPermissions` = unattended execution (no prompts).

## Workflow Pattern

1. Read `~/.paseo/orchestration-preferences.json`
2. Select provider from preferences
3. Optionally create workspace: `paseo_create_workspace(isolation="worktree", ...)`
4. Create agent: `paseo_create_agent(title="...", provider="...", initial_prompt="...")`
5. Agent runs independently → notification on finish
6. Monitor: `paseo_list_agents()`

## Waiting

Paseo agents take 10–30+ minutes. **Do not poll**. Leave `notifyOnFinish=True` (default) and move on to other work. The notification arrives when the agent finishes.

## Related Skills

- **paseo-advisor**: Single agent as second opinion
- **paseo-committee**: Two contrasting agents for root cause analysis
- **paseo-handoff**: Transfer task to fresh agent
- **paseo-loop**: Recurring agent execution
