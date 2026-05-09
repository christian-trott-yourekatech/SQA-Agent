---
name: sqa-resolve
description: Triage untriaged findings, then resolve findings in the requested class. Two modes — `auto` (autonomous fixes via resolve-file subagents) and `interactive` (multi-turn with the user).
argument-hint: auto|interactive
---

# sqa-resolve

You are running the resolve flow using `sqa-tool` and per-file subagents.

## Required argument

The user invokes you as `sqa-resolve auto` or `sqa-resolve interactive`. If the mode isn't specified, ask the user.

## Phase 1 — Autonomous triage

This phase runs in both modes. Triage is autonomous, not user-interactive — its purpose is to *offload* the user, classifying each finding so they only engage with the `interactive`-class set later.

1. Run `sqa-tool list-findings --triage=untriaged --count`. If `0`, skip to Phase 2.
2. Pick `max_agents` (ask user or default to 4).
3. Get the list: `sqa-tool list-findings --triage=untriaged`. Group findings by their primary anchor file (the file containing their anchor — find it by inspecting `related_files` and grepping anchors).
4. Loop in batches of `max_agents` files:
   - Spawn `triage-file` subagents in parallel, one per file with untriaged findings.
   - Wait for all.
   - Continue until no untriaged findings remain (or safety cap of 50 batches).

## Phase 2 — Resolve

### Mode: `auto`

1. Run `sqa-tool list-findings --triage=auto --status=open --count`. If `0`, exit with summary.
2. Get the list: `sqa-tool list-findings --triage=auto --status=open`. Group by anchor file.
3. Loop in batches of `max_agents` files:
   - Spawn `resolve-file` subagents in parallel, one per file.
   - Wait for all.
4. **Optional post-check.** If this project uses a quality-check command, invoke it via Bash. Edit this skill to set the actual command. If a check fails, surface to the user.
5. Run `sqa-tool status` and report.

### Mode: `interactive`

1. Run `sqa-tool list-findings --triage=interactive --status=open`. If empty, exit.
2. **Walk findings sequentially in-skill** (not via subagent — this is the user-engagement endpoint):
   - For each finding, present the `message` and `rationale` to the user.
   - Open a multi-turn conversation. The user can:
     - Say "fix it" or describe how → you apply the fix via Edit/Write, then call `sqa-tool resolve <id> --rationale="..."`.
     - Say `/skip` → move to the next finding.
     - Say `/quit` → exit the loop.
     - Say `/diff` → show `git diff` of unstaged changes.
     - Say `/commit` → run `git add . && git commit` (with a prompted message).
3. After loop ends, optionally run the project quality-check command and report `sqa-tool status`.

## Notes

- All state changes go through `sqa-tool` — never edit `.sqa/findings/*.json` or `.sqa/file_status.json` directly.
- For `resolve auto`, the `resolve-file` subagent applies fixes in source files via Edit and calls `sqa-tool resolve <id>` per finding (which strips the anchor).
- If safety cap (50 batches) is hit, suggest the user re-invoke or wrap with `/loop /sqa-resolve auto`.
