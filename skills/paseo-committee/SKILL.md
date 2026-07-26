---
name: paseo-committee
description: Form a committee of two contrasting external agents to step back, do root cause analysis, and produce a plan. Use when stuck, looping, tunnel-visioning, or facing a hard planning problem.
user-invocable: true
argument-hint: "<problem description or additional context>"
---

# Paseo Committee

Two external agents from contrasting providers (e.g., Claude Opus + Codex GPT-5.4), fresh context, planning a solution in parallel. They stay alive for review after implementation.

**User's additional context:** $ARGUMENTS

## Prerequisites

Read the **paseo** skill. Read `~/.paseo/orchestration-preferences.json` to pick contrasting providers.

## Composition

Two members with different reasoning styles:
- One planning/research-strength provider (from `planning` or `research` category)
- One contrasting high-reasoning provider

## Hard Rules

- **No edits.** Every prompt ends with: "This is analysis only. Do NOT edit, create, or delete any files."
- **Trust the wait.** Agents can reason 15–30 minutes. Long waits mean deep thinking.
- **You are the middleman.** Drive plan → implement → review.

## Phase 1: Plan

Write a problem-level prompt including:
- High-level goal and acceptance criteria
- Constraints and symptoms
- What you tried and why it failed
- Explicit: "do root cause analysis"
- Explicit: "state assumptions, ask why three levels deep"

Create both agents in parallel via `paseo_create_agent` with `[Committee] <task>` titles. Wait for both.

Read both responses. Challenge them:
- "Why does X happen? Symptom or cause?"
- "What did you consider and reject?"

Synthesize:
- Convergence → unified plan
- Divergence → involve the user

## Phase 2: Implement

Default: **implement yourself** using Hermes tools. If the user said "delegate", launch one impl agent via Paseo with the merged plan.

## Phase 3: Review

Send the diff to the committee via `paseo_send_prompt`:
> "Implementation is done. Review changes against the plan. Flag drift or missing pieces. This is analysis only — do NOT edit files."

Apply feedback yourself. Repeat until consensus. After ~10 iterations without convergence, start a fresh committee.
