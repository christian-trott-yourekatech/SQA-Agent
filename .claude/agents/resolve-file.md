---
name: resolve-file
description: Apply fixes for every auto-class finding anchored in one file. Reads the file once, applies all relevant fixes, and resolves each finding via sqa-tool.
tools: Read, Edit, Write, Bash, Grep
---

# resolve-file

You are applying autonomous fixes for all `auto`-class findings anchored in one file.

## Inputs

The skill that invoked you provided one argument: a project-relative file path. That's the file whose `auto`-class open findings you fix.

## Workflow

1. **Find the relevant findings.** Run `sqa-tool findings-for-file <path>` and filter to entries where `triage == "auto"` and `status == "open"` AND whose anchor is in this file (not just an ancestor `.sqa.md` whose `related_files` matches). For findings whose anchor is in this file, the file path will be the right place to fix them.

2. **Read the file** under review.

3. **For each finding**, apply the fix:
   - Read `message` and `rationale` for context — the rationale often contains the exact fix-hint.
   - Apply the fix via Edit (or Write if a wholesale rewrite is needed). Stay focused: only change what's needed for the finding. Don't drag in adjacent improvements.
   - Verify the change is sensible (re-read the affected region if uncertain).
   - Call `sqa-tool resolve <finding_id> --rationale="how this was fixed"`. The tool will strip the anchor comment for you.

4. **Don't modify findings outside this file's scope.** If during your fix you notice a different issue worth reporting, you can record a new finding via `sqa-tool record-finding`, but stay focused on resolving the auto-class items you were dispatched for.

5. **No `mark-reviewed` here.** That's the review skill's job, not resolve's.

## Notes on edits

- Use Edit for surgical changes; only use Write for wholesale rewrites of small files.
- If a fix can't be applied (the rationale is unclear, the surrounding code has changed enough that the finding no longer makes sense, etc.), call `sqa-tool triage <id> interactive --rationale="explain why auto-resolution failed and what a human needs to decide"` instead of `resolve`. This bumps the finding back to the user-engagement queue.

## After

Return a brief summary: file path, count of findings resolved, count of findings bumped back to interactive.
