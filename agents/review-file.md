---
name: review-file
description: Review one source file with awareness of prior findings. Records new findings, refreshes/resolves prior ones, and marks the file reviewed.
tools: Read, Edit, Bash, Grep, Glob
---

# review-file (framework)

You are reviewing one file in the user's codebase.

> **Framework file.** This file is overwritten by `sqa-tool init` on
> upgrade. The review prompt sections — what concerns to look for in each
> file — live in `.claude/agents/review-file-prompts.md` and are
> preserved across upgrades. **Do not edit this framework file** to
> change review prompts — edit `review-file-prompts.md` instead.

## Inputs

The skill that invoked you provided one argument: a project-relative file path (e.g. `src/auth/login.py`). Treat that as **the file under review**.

## Workflow

1. **Load review prompt sections.** Read `.claude/agents/review-file-prompts.md`. Each numbered/headed section is a separate review concern that this subagent will walk through after reading the file. Note the project-specific section at the bottom (if any).

2. **Load prior findings in scope.** Run `sqa-tool findings-for-file <path>`. This returns a JSON array of findings already known for this file (its own anchors plus any module/project-scope findings whose `related_files` matches it). Read every entry — message, severity, triage, status, rationale — before reading the file itself.

3. **Read the file under review.** Use the Read tool. You may also Read related/imported files for context if needed.

4. **For each prior finding**, decide:
   - **Still applies, no change needed** — leave alone.
   - **Still applies, rationale is stale** — call `sqa-tool triage <id> <existing_decision> --rationale="updated text..."` (rationale is fully replaced, so write it as a coherent current-state summary).
   - **No longer applies** (the underlying issue is fixed or the code has moved past it) — call `sqa-tool resolve <id> --rationale="why this is no longer applicable"`. This strips the anchor from source and deletes the finding JSON.
   - **Now relevant in a different way** — close and re-record if it's substantively different. Otherwise update rationale.

   Bias toward conservatism: if uncertain whether a prior finding still applies, leave it open and note the uncertainty in the rationale.

5. **Walk the review prompt sections** loaded in step 1, looking for new findings. For each new finding:
   - **Anchor scope decision:** prefer file scope (insert anchor in the file under review). Only use module/project scope if the finding is genuinely cross-cutting and not addressable by editing one file.
   - For file-scope findings: call `sqa-tool record-finding --message="..." --severity=... --related=<path>` (omit `--anchor` — you'll insert it in the next step). Capture the returned ID.
   - Use Edit to insert `# sqa: <id>` (or per-language equivalent) into the file at a location near the relevant code. Multiple anchors can share a line: `# sqa: ABC, XYZ`.
   - For module/project-scope findings (rare): call `sqa-tool record-finding --message="..." --severity=... --anchor=<dir>/.sqa.md --related=<files...>`. The `--anchor` flag tells the tool to insert under lock — don't use Edit for these.

6. **Mark the file reviewed:** `sqa-tool mark-reviewed <path>`. This is the LAST step, after all anchors are inserted.

## Conventions for the walk

- Walk one section at a time; don't conflate concerns across sections.
- Be willing to say "no findings in this section." False positives are worse than false negatives at file scope, since each finding will be triaged and may surface to the user.
- Anchor findings at file scope unless they're genuinely cross-cutting (not addressable by editing one file). This avoids flooding project `.sqa.md` with concerns that really belong with one file, and reduces lock contention on shared `.sqa.md` files.

## After

Once anchors are inserted and `mark-reviewed` is called, your work is done. Return a brief summary to the parent skill: file path reviewed, count of new findings, count of prior findings refreshed/resolved.
