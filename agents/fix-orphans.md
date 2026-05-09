---
name: fix-orphans
description: Clean up the orphan classes that the sqa-tool can't fix deterministically — anchors with no JSON, JSONs with no anchors, and stale related_files paths.
tools: Read, Edit, Bash, Grep
---

# fix-orphans

You are cleaning up the non-deterministic orphans reported by `sqa-tool orphans`.

## Workflow

1. **Re-run `sqa-tool orphans`** to get a fresh report. The `auto_fixed` portion has already happened (deterministic). Focus on the `reported.*` lists.

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
