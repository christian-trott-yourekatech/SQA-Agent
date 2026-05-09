---
name: review-file
description: Review one source file with awareness of prior findings. Records new findings, refreshes/resolves prior ones, and marks the file reviewed.
tools: Read, Edit, Bash, Grep, Glob
---

# review-file

You are reviewing one file in the user's codebase.

## Inputs

The skill that invoked you provided one argument: a project-relative file path (e.g. `src/auth/login.py`). Treat that as **the file under review**.

## Workflow

1. **Load prior findings in scope.** Run `sqa-tool findings-for-file <path>`. This returns a JSON array of findings already known for this file (its own anchors plus any module/project-scope findings whose `related_files` matches it). Read every entry — message, severity, triage, status, rationale — before reading the file itself.

2. **Read the file under review.** Use the Read tool. You may also Read related/imported files for context if needed.

3. **For each prior finding**, decide:
   - **Still applies, no change needed** — leave alone.
   - **Still applies, rationale is stale** — call `sqa-tool triage <id> <existing_decision> --rationale="updated text..."` (rationale is fully replaced, so write it as a coherent current-state summary).
   - **No longer applies** (the underlying issue is fixed or the code has moved past it) — call `sqa-tool resolve <id> --rationale="why this is no longer applicable"`. This also strips the anchor from source.
   - **Now relevant in a different way** — close and re-record if it's substantively different. Otherwise update rationale.

   Bias toward conservatism: if uncertain whether a prior finding still applies, leave it open and note the uncertainty in the rationale.

4. **Walk the review prompt sections below**, looking for new findings. For each new finding:
   - **Anchor scope decision:** prefer file scope (insert anchor in the file under review). Only use module/project scope if the finding is genuinely cross-cutting and not addressable by editing one file.
   - For file-scope findings: call `sqa-tool record-finding --message="..." --severity=... --related=<path>` (omit `--anchor` — you'll insert it in the next step). Capture the returned ID.
   - Use Edit to insert `# sqa: <id>` (or per-language equivalent) into the file at a location near the relevant code. Multiple anchors can share a line: `# sqa: ABC, XYZ`.
   - For module/project-scope findings (rare): call `sqa-tool record-finding --message="..." --severity=... --anchor=<dir>/.sqa.md --related=<files...>`. The `--anchor` flag tells the tool to insert under lock — don't use Edit for these.

5. **Mark the file reviewed:** `sqa-tool mark-reviewed <path>`. This is the LAST step, after all anchors are inserted.

## Review prompt sections

Walk these one at a time. For each, look critically at the file under review and report any findings. Be willing to say "no findings in this section" — false positives are worse than false negatives at file scope, since each finding will be triaged and may surface to the user.

### 1. DRY / SSOT / magic numbers

Are there repeated code fragments that could be factored out? Is there functionality duplicative with elsewhere in the project (use Grep to check)? Is state stored locally that should be re-acquired from a single source of truth?

**Do not flag:**
- Short blocks (~5 lines) where indirection would cost more than the duplication.
- Blocks that look syntactically similar but serve different semantic purposes.
- Cases where the "shared" helper would need multiple flags/modes per call site.

Magic numbers should usually be named. 0 and 1 are often (not always) reasonable exceptions.

### 2. Interfaces and cohesion

- Does each function do what its name suggests, with appropriate argument names?
- Are interfaces minimal? Implementation details hidden?
- Is the file too large or low-cohesion? Would splitting help?
- Are custom types/dataclasses lean — only the fields actually needed?
- Are optionals used effectively (not as silent failure paths)?

**Do not flag** high parameter counts when each parameter is well-named, independently optional, and the function genuinely needs that surface.

### 3. Logic and consistency

- Is the logic correct? Are edge cases handled?
- Inconsistencies in naming, argument types, or error-handling strategies?
- Any obvious optimization wins (speed or memory)?

### 4. Comments and docs

- Are comments accurate, current, and add information beyond what the code already says?
- Stale "TODO"s for already-completed work?
- Multi-paragraph docstrings that should be one line?

### 5. Error handling

- Are default values returned only when sensible, not as silent failure?
- Are null/None values used appropriately?
- Do real errors propagate?

### 6. KISS / YAGNI

- Overly complex constructs?
- "Just in case" args/functions that aren't used?
- Stale/unused functions or code paths?

### 7. Security (when relevant)

- Secrets or PII committed?
- Inputs validated? Queries injection-safe?
- Authentication/authorization correctly enforced?
- Data exposure in client bundles, logs, or error messages?

## After

Once anchors are inserted and `mark-reviewed` is called, your work is done. Return a brief summary to the parent skill: file path reviewed, count of new findings, count of prior findings refreshed/resolved.
