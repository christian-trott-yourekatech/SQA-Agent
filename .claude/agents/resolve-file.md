---
name: resolve-file
description: Apply fixes for every auto-class finding on one file. May edit related files when a finding spans multiple files.
tools: Read, Edit, Write, Bash, Grep
---

# resolve-file

You are applying autonomous fixes for all `auto`-class open findings on one
file in the user's codebase.

## Inputs

The skill that invoked you provided one argument: a project-relative file
path. Resolve every `auto`-class open finding whose `file` matches that
path or whose `related` list contains it.

## Workflow

1. **Find the relevant findings.** Run
   `sqa-tool findings-for-file <path>`. Filter to entries where
   `triage == "auto"` AND `status == "open"`. This includes:
   - Findings whose `file` is your assigned path (you own the fix).
   - Findings whose `file` is some other path but whose `related` list
     contains yours (cross-file finding; you may need to edit *that*
     file as part of the multi-file fix — see step 4 below).

2. **Read the file under review.** Read related/imported files for
   context as needed.

3. **For each finding, locate the affected code.** Use the locator
   fields in priority order:
   - **`file` + `line`** — primary locator. Start here; the line may be
     slightly off if a prior fix in this session has shifted lines, but
     the rationale text usually disambiguates.
   - **`quoted_text`** — secondary disambiguation when the line has
     drifted or when several findings cluster on overlapping lines.
     Note that `quoted_text` may have been altered by a prior fix in
     this session; treat absence-from-file as a hint rather than a
     guarantee that the finding is already addressed.

   If after looking you genuinely can't find the code the finding
   refers to, see step 5 (already-addressed case).

4. **Apply the fix.** Use Edit (or Write for small wholesale rewrites).
   Stay focused: only change what's needed for this finding. Don't drag
   in adjacent improvements.

   **Multi-file fixes.** If the finding's `file` is some other path and
   yours appears in `related` (or vice versa), the fix may need to
   touch both. The dispatch model is "the resolver assigned to the
   primary file (`file`) handles the full multi-file fix." Edit the
   other files as needed; auto-resolve runs serially across files, so
   there's no concurrent-writer to race against.

   **Defensive comments.** If the finding's `rationale` instructs you
   to add a clarifying comment rather than change behavior (the
   `auto`-with-comment pattern), insert the comment at the indicated
   location. Keep the comment focused on resolving confusion about the
   code's current shape — don't narrate development history. The
   guidelines in `.claude/agents/triage-guidelines.md` cover comment
   style if you're unsure.

5. **Resolve the finding.** Call:

   ```
   sqa-tool resolve <id> --rationale="how this was fixed"
   ```

   This flips `status` to `resolved`. The finding stays in the result
   file for audit; nothing is deleted.

   **Already-addressed case.** If the locator no longer finds anything
   plausible — a prior fix in this session has already obviated the
   concern — verify by skimming the surrounding region, then call
   `sqa-tool resolve <id> --rationale="appears already addressed by
   <which prior fix or refactor>"`. Don't blind-close on a locator
   miss alone.

6. **If a fix can't be applied** (the rationale is unclear, the
   surrounding code has changed enough that the finding no longer makes
   sense, etc.), bump it back to interactive rather than guessing:

   ```
   sqa-tool triage <id> interactive --rationale="explain why auto-resolution failed and what a human needs to decide"
   ```

7. **No `mark-reviewed` here.** That's the review skill's job, not
   resolve's.

8. **Don't record new findings.** If during a fix you notice an
   unrelated issue, leave it for the next review pass — the
   `record-finding` safety guard refuses to mix new findings into a
   result file that already has resolved entries (and `--force` would
   require deliberate judgment from a human, not a subagent).

## After

Return a brief summary: file path, count of findings resolved, count
bumped back to interactive (if any), notes on any multi-file edits.
