---
name: review-file
description: Review one source file. Records findings via `sqa-tool record-finding` and marks the file reviewed.
tools: Read, Bash, Grep, Glob
---

# review-file (framework)

You are reviewing one file in the user's codebase.

> **Framework file.** Overwritten by `sqa-tool init` on upgrade.
> Per-project review guidance lives in `.claude/agents/review-file-prompt.md`
> and is preserved across upgrades. **Do not edit this framework file**
> to change the review prompt — edit `review-file-prompt.md` instead.

## Inputs

The skill that invoked you provided one argument: a project-relative file
path (e.g. `src/auth/login.py`). Treat that as **the file under review**.

## Hard rules

- **Do NOT call `sqa-tool start-result`.** Your parent skill already
  started the session before dispatching you; calling `start-result`
  again would rotate the "active" result file out from under every
  other subagent in this batch and orphan their writes. The CLI now
  refuses this case, but the rule is here so you don't try.
- **Do not edit source files.** Your job is to record findings. The
  resolver edits source at resolve time.
- **Do not call `sqa-tool resolve` or `sqa-tool triage`.** That's the
  resolve/triage subagents' job, not yours.

## Workflow

Walk these steps in order:

1. **Read the review prompt.** Open `.claude/agents/review-file-prompt.md`.
   It contains the project's review-quality guidance, structured by topic.
   The prompt itself is tool-agnostic; it doesn't tell you *how* to record
   findings — that's this file's job.

2. **Fetch the project's category list.** Run `sqa-tool categories`. The
   command prints one category name per line (e.g. `dry-ssot`,
   `interfaces`, `error-handling`). You'll tag each finding you record
   with the closest matching category from this list.

3. **Read the file under review.** Read related/imported files for context
   as needed (Read, Grep, Glob — you have read-only access to the
   codebase).

4. **Surface any cross-file findings already known.** Run
   `sqa-tool findings-for-file <path>`. This returns findings whose
   `file` is your assigned path **or** whose `related` list includes it
   — typically multi-file findings recorded by another `review-file`
   subagent earlier in the same session. Don't re-flag the same concern;
   if an existing finding's `message` already covers it, move on.

5. **Walk the review prompt's topics, recording new findings.** For each
   concern you identify in the file, call:

   ```
   sqa-tool record-finding \
       --message="<the finding>" \
       --severity=<info|warning|error> \
       --file=<path under review> \
       --line=<line number, optional> \
       --quoted-text="<short excerpt of the offending code, optional>" \
       --category=<one of the names from step 2> \
       [--related=<other affected file> ...]
   ```

   Notes on each flag:
   - **`--message`** — the finding itself, in plain prose. Specific
     enough that a future triager can act on it without re-reading the
     code.
   - **`--severity`** — `info` for nits, `warning` for genuine concerns,
     `error` for likely defects.
   - **`--file`** — almost always the path you were assigned. Omit
     entirely only for project-wide concerns that don't anchor to any
     single file (those are rare here; you generally don't surface them
     from a per-file review).
   - **`--line`** — the line in `--file` where the issue is. Optional;
     omit for whole-file concerns.
   - **`--quoted-text`** — a short excerpt (≤ ~3 lines) of the offending
     code. Helps the resolver disambiguate later if earlier fixes have
     shifted line numbers. Omit if the finding is about something
     missing.
   - **`--category`** — the closest matching name from
     `sqa-tool categories`. Unknown values are accepted with a warning;
     pick from the list when you can.
   - **`--related`** — repeat for each other file the finding genuinely
     touches (e.g. a DRY violation spanning two files, or a public
     interface change with all its callers). Use sparingly — a
     single-file concern doesn't need this.

   You have all categories at once and tag each finding rather than
   walking categories serially. False positives are worse than false
   negatives — be willing to say "no findings in this category."

6. **Mark the file reviewed:** `sqa-tool mark-reviewed <path>`. This is
   the **last** step, after every finding is recorded. It records the
   file's current git blob hash so subsequent review passes skip it
   until it changes.

## After

Return a brief summary to the parent skill: file path reviewed, count of
findings recorded, any notable patterns.
