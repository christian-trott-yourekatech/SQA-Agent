---
name: sqa-review
description: Run a review pass over the project — dispatches review-file subagents over files that have changed since last review, with persistent findings anchored in source via the sqa-tool CLI.
---

# sqa-review (framework)

You are running a project review using `sqa-tool` and the `review-file` subagent.

> **Framework file.** This file is overwritten by `sqa-tool init` on
> upgrade. Project-specific configuration (quality-check command,
> conventions) lives in `.claude/skills/sqa-review/project.md` and is
> preserved across upgrades. **Do not edit this framework file** for
> project-specific settings — edit `project.md` instead.

## Your job per invocation

1. **Read project configuration.** Read `.claude/skills/sqa-review/project.md`. Extract the quality-check command from its "Quality-check command" section (the bash code block). Note any project-specific conventions in the file for use later.

2. **Pre-review quality check.** Run the quality-check command from step 1 via Bash, before any LLM work. Getting deterministic-tool issues out of the way first means the review agent doesn't burn tokens flagging things a linter or type-checker would catch, and the source it reviews is in a known-good state.

   If the check fails, **stop and surface the failures to the user.** Do not proceed to the LLM review until the project is green — fix the deterministic issues first (via direct edits or a separate session). The reviewer's value is in finding things deterministic tools miss; it shouldn't be wasted on items the tools already flag.

3. **Run orphans cleanup.** Invoke `sqa-tool orphans`. The tool auto-fixes the deterministic class. If the `reported.*` lists are non-empty, dispatch a `fix-orphans` subagent before proceeding. If they're empty, skip directly to step 4.

4. **Pick parallelism.** Ask the user (in chat) what `max_agents` to use, or use `4` as the default if running non-interactively. Higher = faster but more aggressive on quota.

5. **Drive the bounded review loop.** Repeat:
   - Run `sqa-tool needs-review --count`. If `0`, exit the loop.
   - **Tell the user the count** at the start of each iteration in a single short line, e.g. `12 files remaining to review.` This gives them a live progress signal across batches.
   - Run `sqa-tool needs-review --limit=<max_agents>` to get the next batch of files.
   - Spawn one `review-file` subagent per file in the batch, **in parallel** (single message with multiple Agent tool calls). Wait for all to complete.
   - Continue until `needs-review --count` returns `0` or the safety cap (50 batches) is reached.

6. **Report summary.** Run `sqa-tool status` and present the output to the user.

If the safety cap was reached and the loop exited early, tell the user that more files remain and suggest running `/loop /sqa-review` to continue automatically.

## Notes

- Each `review-file` subagent is one-shot and self-contained. It calls `sqa-tool` directly to record/triage/resolve findings; you don't intermediate.
- Findings are persistent — they live in `.sqa/findings/<id>.json` and reappear in subsequent reviews.
- Anchors live in source files (`# sqa: <id>`) or `.sqa.md` metadata files. The `review-file` subagent inserts and updates these as needed.
