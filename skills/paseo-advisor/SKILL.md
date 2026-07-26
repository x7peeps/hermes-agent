---
name: paseo-advisor
description: Spin up a single external agent as an advisor — second opinion on the current task. Use when the user says "advisor", "second opinion", "what does X think", or wants an outside take without delegating the work itself.
user-invocable: true
argument-hint: "[--provider <name>] <question or topic>"
---

# Paseo Advisor

Spawn a single external coding agent (Claude Code, Codex, etc.) through Paseo to provide a second opinion. The advisor analyzes and gives judgment — you decide what to do.

**User's request:** $ARGUMENTS

## Prerequisites

Read the **paseo** skill first. Before choosing a provider, read `~/.paseo/orchestration-preferences.json` unless the user explicitly named a provider.

## Picking the Advisor

1. **User named one** (`--provider claude/opus`) → use it.
2. **Otherwise** resolve from preferences:
   - Design / approach question → `planning`
   - "Did I miss something" review → `audit`
   - "Is this even right" → `research`
3. **Contrast helps.** If your own provider matches what preferences would pick, swap to a different family.

## The Briefing

The advisor has zero context. Make it self-contained:

- The question, sharply stated
- What you've considered and ruled out
- Relevant file paths (don't paste — let the agent read)
- Explicit ask: "give me a recommendation, with reasoning"

End with:
```
This is analysis only. Do NOT edit, create, or delete any files. Do NOT write code.
```

## Launch

1. Call `paseo_create_agent` with title `[Advisor] <topic>`, the briefing as `initial_prompt`, and the selected provider
2. Leave `notify_on_finish=True` (default)
3. Wait for the advisor to finish
4. Read the response, synthesize for the user: advisor's verdict + your recommendation

## Persistent Advisor

If the user wants ongoing input, don't archive after the first reply. Send follow-ups with `paseo_send_prompt` when needed. Archive when the topic shifts.
