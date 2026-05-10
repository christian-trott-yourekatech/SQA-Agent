---
name: fix-orphans
description: Clean up the orphan classes that the sqa-tool can't fix deterministically — anchors with no JSON, JSONs with no anchors, and stale related_files paths.
tools: Read, Edit, Bash, Grep
---

# fix-orphans

You are cleaning up the non-deterministic orphans reported by `sqa-tool orphans`.

## Source of truth

`sqa-tool orphans` is the **only** authoritative source for orphans. It uses a string-literal-aware scanner that ignores anchor-format text inside Python docstrings, markdown fenced/inline code, and other documentation contexts where literal `sqa: <id>` is just an example. **Never act on orphan signals from anywhere else** — not from your own `grep`, not from a `Read` of the file, not from a parent skill's commentary. If the parent dispatched you with a description like "ABCDE looks orphaned in foo.py", verify it against `sqa-tool orphans` output before doing anything. If the tool doesn't flag it, the parent was wrong; report back and exit.

## Never rewrite anchor-format text

If a file has `sqa: <id>` text that you believe shouldn't be a real anchor (e.g. inside a docstring, test fixture, or doc example), the **wrong** fix is to mutate the literal text — replacing `sqa:` with `sqa<colon>`, escaping the colon, etc. The right fixes, in order of preference, are:

1. **Trust the scanner.** If the text is inside a Python string literal or markdown fenced/inline code, `sqa-tool orphans` already ignores it. There's nothing to fix.
2. **Delete the anchor** (`Edit` to remove the comment) if the literal text is in a regular comment and is genuinely a stale anchor with no JSON.
3. **Use a non-conforming placeholder** (e.g. `sqa: <id>` with angle brackets, since `<` isn't in the base32 alphabet) only if you're editing example text that needs to read like an anchor for documentation purposes but must not match `ANCHOR_RE`.

Never invent placeholder syntax of your own (`<colon>`, escapes, zero-width chars). It corrupts documentation, accumulates self-referential explanations, and the next reader has no idea why the literal looks broken.

## Workflow

1. **Re-run `sqa-tool orphans`** to get a fresh report. The `auto_fixed` portion has already happened (deterministic). Focus on the `reported.*` lists. **If every list is empty, you're done — do not look for orphans elsewhere.**

2. **For each `findings_without_anchors` entry** (a finding JSON exists but no anchor anywhere):
   - Run `sqa-tool show-finding <id>` to see the message, severity, and `related_files`.
   - Decide:
     - **The finding is still meaningful and references a real file** → re-insert an anchor in the appropriate location. For file-scope, Edit the file to add `# sqa: <id>` near relevant code. For module/project-scope, use `sqa-tool record-finding` is the wrong tool here (it allocates a new ID); instead Edit the appropriate `.sqa.md` to add `<!-- sqa: <id> -->`.
     - **The finding's referenced files no longer exist or the issue has moved past relevance** → close it: `sqa-tool resolve <id> --rationale="closing as orphaned: <why>"`.

3. **For each `anchors_without_findings` entry** (an anchor in source/markdown but no JSON file):
   - The anchor is dead — no finding metadata exists. Remove the anchor from the listed file(s). Edit the file to delete the ID from the comment (or the whole comment if it's the only ID).

4. **For each `stale_related_files` entry** (a finding's `related_files` references a path that no longer exists):
   - Run `sqa-tool show-finding <id>` and decide:
     - **The path was renamed** → figure out the new path (use Grep / Bash to find it, or check `git log --follow`) and update `related_files`. Re-record by using `sqa-tool triage <id> <existing_decision> --rationale="..."` is wrong — that doesn't change related_files. Instead, since the design's only finding-mutator interfaces don't expose related_files updates, recreate the finding with corrected metadata: read its full state, `sqa-tool resolve <id>` (or just close with a "migrated to <new_id>" rationale), then `sqa-tool record-finding ...` with the corrected `--related`. Insert a fresh anchor for the new ID.

       *(Note: if this becomes common, a future tool subcommand for editing `related_files` directly should be added. For now, recreate is the workaround.)*
     - **The path was deleted and the finding no longer applies** → `sqa-tool resolve <id> --rationale="referenced file was deleted; finding no longer applicable"`.

5. **Verify by re-running `sqa-tool orphans`.** The reported lists should now be empty (or contain only entries you couldn't reasonably address).

## After

Return a brief summary: count fixed in each class, count left unaddressed (and why).
