---
name: sqa-review
description: Run a review pass over the project — dispatches review-file subagents over files that have changed since last review, with persistent findings anchored in source via the sqa-tool CLI.
---

# sqa-review

You are running a project review using `sqa-tool` and the `review-file` subagent.

## Your job per invocation

1. **Run orphans cleanup.** Invoke `sqa-tool orphans`. The tool auto-fixes the deterministic class. If the `reported.*` lists are non-empty, dispatch a `fix-orphans` subagent before proceeding with the rest of the review. If they're empty, skip directly to step 2.

2. **Pick parallelism.** Ask the user (in chat) what `max_agents` to use, or use `4` as the default if running non-interactively. Higher = faster but more aggressive on quota.

3. **Drive the bounded review loop.** Repeat:
   - Run `sqa-tool needs-review --count`. If `0`, exit the loop.
   - Run `sqa-tool needs-review --limit=<max_agents>` to get the next batch of files.
   - Spawn one `review-file` subagent per file in the batch, **in parallel** (single message with multiple Agent tool calls). Wait for all to complete.
   - Continue until `needs-review --count` returns `0` or the safety cap (50 batches) is reached.

4. **Optional post-check.** If this project uses a quality-check command (e.g. `./runtools.sh`, `make check`, `npm test`), invoke it via Bash. Edit this skill to set the actual command for the project, or remove the post-check step if not needed.

5. **Report summary.** Run `sqa-tool status` and present the output to the user.

If the safety cap was reached and the loop exited early, tell the user that more files remain and suggest running `/loop /sqa-review` to continue automatically.

## Notes

- Each `review-file` subagent is one-shot and self-contained. It calls `sqa-tool` directly to record/triage/resolve findings; you don't intermediate.
- Findings are persistent — they live in `.sqa/findings/<id>.json` and reappear in subsequent reviews.
- Anchors live in source files (`# sqa: <id>`) or `.sqa.md` metadata files. The `review-file` subagent inserts and updates these as needed.
