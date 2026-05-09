---
name: sqa-resolve
description: Triage untriaged findings, then resolve findings in the requested class. Two modes — `auto` (autonomous fixes via resolve-file subagents) and `interactive` (multi-turn with the user).
argument-hint: auto|interactive
---

# sqa-resolve (framework)

You are running the resolve flow using `sqa-tool` and per-file subagents.

> **Framework file.** This file is overwritten by `sqa-tool init` on
> upgrade. Project-specific configuration (quality-check command,
> conventions) lives in `.claude/skills/sqa-resolve/project.md` and is
> preserved across upgrades. **Do not edit this framework file** for
> project-specific settings — edit `project.md` instead.

## Required argument

The user invokes you as `sqa-resolve auto` or `sqa-resolve interactive`. If the mode isn't specified, ask the user.

## Phase 0 — Pre-resolve baseline check

Before any triage or resolution work:

1. Read `.claude/skills/sqa-resolve/project.md`. Extract the quality-check command from its "Quality-check command" section. Note any project-specific conventions for use later.
2. Run that command via Bash **once** to establish a clean baseline. Per-finding regression checks during the resolve phase only have value if the project starts green — otherwise pre-existing failures get conflated with regressions.
3. If the check fails at baseline, **stop and surface the failures to the user.** Do not proceed to Phase 1 until the project is green. Either fix the failures directly, or have the user fix them in a separate session, before re-invoking `sqa-resolve`. The triage and resolve phases assume a clean starting state.

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
3. **Resolve files one at a time, sequentially, with per-finding quality checks.** For each file in the group:
   - Spawn one `resolve-file` subagent. Wait for it to complete before starting the next.
   - **Do not parallelize this step.** Auto-resolve is the one phase that writes substantively to source code, and many real fixes span files (DRY extractions, renames, SSOT consolidations, following established patterns). Parallel `resolve-file` subagents can race on cross-file edits, produce semantic conflicts, or drift the very pattern they're meant to follow. Serial dispatch preserves correctness.
   - **After each subagent completes, run the project quality-check command** (the same one from Phase 0). If it fails, **fix the regressions before moving on** — either directly via Edit, or by spawning another short-scoped subagent to address them. Do *not* proceed to the next file with a known-failing check; regressions accumulate and become hard to attribute.
4. After the loop ends, run `sqa-tool status` and report. Optionally run the quality-check one more time as a final sanity check.

### Mode: `interactive`

1. Run `sqa-tool list-findings --triage=interactive --status=open`. If empty, exit.
2. **Walk findings sequentially in-skill** (not via subagent — this is the user-engagement endpoint):
   - For each finding, present the `message` and `rationale` to the user, then ask how they'd like to proceed.
   - The user replies in **natural language**, not slash commands. Interpret intent:
     - **Apply a fix** — the user says "fix it," "go ahead," "do it," "yes," gives a specific fix instruction, or otherwise indicates the finding should be resolved. Apply the fix via Edit/Write, then call `sqa-tool resolve <id> --rationale="<what was changed and why>"`.
     - **Skip / move on** — "skip," "next," "leave it," "come back to this later." Move to the next finding without changing state.
     - **Stop the walk** — "quit," "stop," "let's pause," "I'm done for now." Exit the loop and report progress.
     - **Show the diff** — "show me the diff," "what's changed," "diff." Run `git diff` (or `git diff --staged` if appropriate) and present it.
     - **Commit progress** — "commit," "let's commit what we have," "save progress." Stage and commit (`git add .` plus a commit with a message either provided by the user or that you suggest based on the resolved findings).
     - **Re-classify** — "this is actually auto," "ignore this one," "this isn't really an issue." Use `sqa-tool triage <id> auto|ignore --rationale="..."` to bump the finding into a different bucket. (For ignore, capture *why* in the rationale per the triage guidance.)
     - **Ask a clarifying question** — answer it; don't assume the answer means "fix it."
   - Don't expect exact phrasing. Use judgment to interpret what the user wants. If genuinely unclear, ask.
   - **After every fix that lands, run the project quality-check command** (the same one from Phase 0). If it fails, **fix the regressions before moving on to the next finding** — work it through with the user the same way you'd work the original finding. Do not advance to the next finding with a known-failing check; the user benefits from clean attribution between each fix and any breakage it causes.
3. After the loop ends (or the user stops it), run `sqa-tool status` and report. Optionally run the quality-check one final time as a sanity check.

## Notes

- All state changes go through `sqa-tool` — never edit `.sqa/findings/*.json` or `.sqa/file_status.json` directly.
- For `resolve auto`, the `resolve-file` subagent applies fixes in source files via Edit and calls `sqa-tool resolve <id>` per finding (which strips the anchor and deletes the JSON).
- If safety cap (50 batches) is hit, suggest the user re-invoke or wrap with `/loop /sqa-resolve auto`.
