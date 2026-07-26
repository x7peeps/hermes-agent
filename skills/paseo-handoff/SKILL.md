---
name: paseo-handoff
description: Hand off the current task to a fresh external agent with full context. Use when the user says "handoff", "hand off", "hand this to", or wants to pass work to another agent.
user-invocable: true
---

# Paseo Handoff

Transfer the current task — context, decisions, failed attempts, constraints — to a fresh external agent. The receiving agent starts with **zero context**, so the handoff prompt must be self-contained.

**User's arguments:** $ARGUMENTS

## Prerequisites

Read the **paseo** skill. Read `~/.paseo/orchestration-preferences.json` to pick the right provider.

## Parsing Arguments

1. **Provider** — explicit user request first; otherwise resolve from `impl` preference
2. **Isolation** — "in a worktree" / "worktree" → create workspace with `isolation="worktree"`
3. **Task description** — anything else the user said

## The Handoff Prompt

Include everything the receiving agent needs:

```
## Task
[Imperative description]

## Context
[Why this task exists]

## Relevant files
- `path/to/file.py` — [what it is and why it matters]

## Current state
[What's done, what works, what doesn't]

## What was tried
- [Approach] — [why it failed]

## Decisions
- [Decision — rationale]

## Acceptance criteria
- [ ] [Criterion]

## Constraints
- [Must-not / must-preserve]
```

Preserve task semantics. Investigate-only → "DO NOT edit files." Fix → "implement the fix."

## Launch

1. Optionally create workspace: `paseo_create_workspace(isolation="worktree", ...)`
2. Call `paseo_create_agent` with `[Handoff] <task>` title, the briefing as `initial_prompt`
3. Return the agent ID to the user, explaining it runs independently
4. The agent notifies on finish — don't wait unless the user wants to follow along
