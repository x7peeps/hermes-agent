---
name: paseo-loop
description: Run recurring agent tasks on a schedule through Paseo. Use for build watching, PR babysitting, periodic checks, and any work that needs to happen on a cadence.
user-invocable: true
argument-hint: "--cron <expression> [--provider <name>] <task description>"
---

# Paseo Loop

Schedule recurring agent execution on the Paseo daemon. Unlike Hermes cron jobs (which run the agent itself), Paseo loops spawn a **fresh external coding agent** each run.

**User's request:** $ARGUMENTS

## Prerequisites

Read the **paseo** skill. Read `~/.paseo/orchestration-preferences.json` for provider selection.

## When to Use

- **Build watching**: `--cron "*/15 * * * *" "check if the build passes"`
- **PR babysitting**: `--cron "*/30 * * * *" "monitor PR CI status, report failures"`
- **Periodic checks**: `--cron "0 */4 * * *" "scan for new issues in the repo"`
- **Recurring maintenance**: `--cron "0 9 * * 1" "run security audit on dependencies"`

## Provider Selection

1. User explicit (`--provider codex/gpt-5.4`) → use it
2. Otherwise:
   - Audit/checks → `audit` category
   - Research/scan → `research` category
   - Maintenance/fixes → `impl` category

## Launch

Use `paseo_create_agent` or the Paseo daemon's native schedule API:

```
paseo_create_agent(
    title="[Loop] <task>",
    provider=<resolved_provider>,
    initial_prompt="<task description>",
    notify_on_finish=True,
)
```

For true cron-scheduled recurring runs, the Paseo daemon has native `create_schedule` support. The Hermes integration can also use its own `cronjob` tool to re-trigger.

## Prompt Design

Keep loop prompts self-contained and stateless:
- What to check
- Where to look
- How to report results
- What actions to take (if any)

Example:
```
Check the CI status for the latest commit on the main branch.
If any checks are failing, report which checks failed and the error messages.
If all checks pass, say "All green."
This is a status check only — do NOT edit files.
```

## Monitoring

The Paseo daemon notifies on each run's completion. You can also call `paseo_list_agents()` to see recent loop executions.
