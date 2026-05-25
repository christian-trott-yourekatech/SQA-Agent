---
name: sqa-resolve
description: Triage untriaged findings, then resolve findings in the requested class. Two modes — `auto` (autonomous fixes via resolve-file/resolve-general subagents) and `interactive` (multi-turn with the user).
argument-hint: auto|interactive
---

# sqa-resolve (framework)

You are running the resolve flow over the most recent review session's
result file, using `sqa-tool` and per-file subagents.

> **Framework file.** Overwritten by `sqa-tool init` on upgrade.
> Project-specific configuration (quality-check command, conventions)
> lives in `.claude/skills/sqa-resolve/project.md` and is preserved
> across upgrades. **Do not edit this framework file** for
> project-specific settings — edit `project.md` instead.

## Required argument

The user invokes you as `sqa-resolve auto` or `sqa-resolve interactive`.
If the mode isn't specified, ask the user.

## Phase 0 — Pre-resolve baseline check

Before any triage or resolution work:

1. Read `.claude/skills/sqa-resolve/project.md`. Extract the
   quality-check command from its "Quality-check command" section. Note
   any project-specific conventions for use later.
2. Run that command via Bash **once** to establish a clean baseline.
   Per-finding regression checks during the resolve phase only have
   value if the project starts green — otherwise pre-existing failures
   get conflated with regressions.
3. If the check fails at baseline, **stop and surface the failures to
   the user.** Do not proceed to Phase 1. Either fix the failures
   directly, or have the user fix them in a separate session, before
   re-invoking `sqa-resolve`.

If `sqa-tool active-result` returns no path, there's no review session
to resolve against — surface that and stop.

## Phase 1 — Autonomous triage

This phase runs in both modes. Triage is autonomous, not user-interactive
— its purpose is to *offload* the user, classifying each finding so they
only engage with the `interactive`-class set later. Triage subagents
**do not edit source files**, so this phase is safe to parallelize.

1. Run `sqa-tool list-findings --triage=untriaged --count`. If `0`,
   skip to Phase 2.

2. **Pick parallelism.** Use the same `max_agents` value from the
   review pass (or ask if you haven't been told; default 4).

3. **Dispatch in two streams in parallel:**
   - **File-scoped untriaged findings:** Get the list with
     `sqa-tool list-findings --triage=untriaged`. Group by the `file`
     field (skip entries where `file` is `null` — those are general
     findings). Loop in batches of `max_agents` files; spawn one
     `triage-file` subagent per file in the batch, in parallel.
   - **General untriaged findings** (`file == null`): if any exist,
     spawn a single `triage-general` subagent. It handles the full set
     in one pass.

   The general subagent can run concurrently with the file batches —
   they don't touch the same data (`sqa-tool triage` is fcntl-locked
   on the result file).

4. Continue until `sqa-tool list-findings --triage=untriaged --count`
   returns `0`, or the safety cap (50 batches) is hit.

## Phase 2 — Resolve

### Mode: `auto`

1. **File-scoped auto resolves, serial.** Run
   `sqa-tool list-findings --triage=auto --status=open` and group by
   `file`. For each file (skipping `file == null` entries):
   - Spawn one `resolve-file` subagent. Wait for it to complete before
     starting the next.
   - **Do not parallelize this step.** Auto-resolve is the one phase
     that writes substantively to source code, and many real fixes
     span files (DRY extractions, renames, SSOT consolidations,
     following established patterns). Parallel `resolve-file`
     subagents can race on cross-file edits or produce semantic
     conflicts. Serial dispatch preserves correctness.
   - **After each subagent completes, run the project quality-check
     command.** If it fails, **fix the regressions before moving on**
     — either directly via Edit, or by spawning a short-scoped
     subagent. Do *not* proceed to the next file with a known-failing
     check; regressions accumulate and become hard to attribute.

2. **General auto resolves, last.** After all file-scoped work
   completes, if any `auto` open findings with `file == null` remain,
   spawn a single `resolve-general` subagent. It runs sequentially
   (general findings often touch shared docs). Run the quality-check
   afterwards and fix any regressions before reporting.

   The order matters: code first, then docs. General findings often
   document or describe code; doing them after the code is in final
   state means the docs are written against the *final* shape, not a
   moving target.

3. After both steps, run `sqa-tool status` and report.

### Mode: `interactive`

1. Run `sqa-tool list-findings --triage=interactive --status=open`. If
   empty, exit.

2. **Walk findings sequentially in-skill** (not via subagent — this is
   the user-engagement endpoint):
   - For each finding, present the `message` and `rationale` to the
     user, then ask how they'd like to proceed.
   - The user replies in **natural language**, not slash commands.
     Interpret intent:
     - **Apply a fix** — the user says "fix it," "go ahead," "do it,"
       "yes," gives a specific fix instruction, or otherwise
       indicates the finding should be resolved. Apply the fix via
       Edit/Write, then call
       `sqa-tool resolve <id> --rationale="<what was changed and why>"`.
     - **Skip / move on** — "skip," "next," "leave it," "come back to
       this later." Move to the next finding without changing state.
     - **Stop the walk** — "quit," "stop," "let's pause," "I'm done
       for now." Exit the loop and report progress.
     - **Show the diff** — "show me the diff," "what's changed,"
       "diff." Run `git diff` (or `git diff --staged` if appropriate)
       and present it.
     - **Commit progress** — "commit," "let's commit what we have,"
       "save progress." Stage and commit (`git add .` plus a commit
       message either provided by the user or that you suggest based
       on the resolved findings).
     - **Re-classify** — "this is actually auto," "ignore this one,"
       "this isn't really an issue." Use
       `sqa-tool triage <id> auto|ignore --rationale="..."` to bump
       the finding into a different bucket. (For ignore, capture
       *why* in the rationale per the triage guidance.)
     - **Ask a clarifying question** — answer it; don't assume the
       answer means "fix it."
   - Don't expect exact phrasing. Use judgment to interpret what the
     user wants. If genuinely unclear, ask.
   - **After every fix that lands, run the project quality-check
     command.** If it fails, **fix the regressions before moving on
     to the next finding** — work it through with the user the same
     way you'd work the original finding. Do not advance to the next
     finding with a known-failing check; the user benefits from clean
     attribution between each fix and any breakage it causes.

3. After the loop ends (or the user stops it), run `sqa-tool status`
   and report.

## Notes

- All state changes go through `sqa-tool`. Never edit the result file
  (`.sqa/result_<timestamp>.json`) or `.sqa/file_status.json` directly.
- `sqa-tool triage <id> ignore` automatically transitions the finding
  to `status=resolved` in the same call; you don't need a separate
  `resolve` step for ignored items.
- The `sqa-tool` commands print one-line "hint:" suggestions to stderr
  at each gate query (e.g. `list-findings --triage=auto --status=open
  --count`). They confirm which phase the count belongs to and whether
  it is complete; they do not prescribe parallelism or subagent dispatch
  — those rules live here in the skill markdown.
- If safety cap (50 batches) is hit, suggest the user re-invoke or
  wrap with `/loop /sqa-resolve auto`.
