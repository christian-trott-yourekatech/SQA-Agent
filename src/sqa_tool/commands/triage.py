"""sqa-tool triage / resolve — finding state transitions."""

import argparse
from pathlib import Path

from sqa_tool import anchors, findings, git_ops


def _find_files_with_anchor(project_root: Path, finding_id: str) -> list[Path]:
    # OSError is intentionally NOT caught here. resolve() is destructive
    # (strips anchors then deletes the finding JSON), so silently skipping an
    # unreadable file would split the action — leaving an orphan anchor with
    # no matching JSON and no warning. orphans._collect_anchored_ids does
    # suppress OSError because that path is read-only and self-healing.
    out = []
    for _rel, path in git_ops.walk_tracked_files(project_root):
        try:
            ids = anchors.find_anchors_for_orphan_scan(path)
        except UnicodeDecodeError:
            continue
        if finding_id in ids:
            out.append(path)
    return out


def triage(project_root: Path, args: argparse.Namespace) -> int:
    try:
        f = findings.load_finding(project_root, args.id)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", flush=True)
        return 1
    f.triage = args.decision
    f.rationale = args.rationale
    findings.save_finding(project_root, args.id, f)
    print(f"triaged {args.id}: {args.decision}", flush=True)
    return 0


def resolve(project_root: Path, args: argparse.Namespace) -> int:
    """Mark a finding resolved: strip its anchors from source and delete the JSON.

    The `--rationale` argument is accepted (and echoed back as confirmation
    output) but not persisted — under the "git is the audit trail" model, the
    explanation for the fix lives in the user's commit message rather than in
    a JSON field that gets deleted moments later.
    """
    # Reject malformed IDs up front so an invalid ID can't slip into the
    # destructive cleanup path below — load_finding raises ValueError for
    # both invalid-ID-format and corrupt-JSON, but only the second deserves
    # to proceed.
    if not findings.is_valid_id(args.id):
        print(f"error: Invalid finding ID: {args.id!r}", flush=True)
        return 1
    try:
        findings.load_finding(project_root, args.id)
    except FileNotFoundError as e:
        # Unknown ID — abort. We don't perform destructive cleanup for an ID
        # whose JSON doesn't exist (likely a typo, or stale anchors from a
        # previously-resolved finding that should be cleaned via the orphans
        # path instead).
        print(f"error: {e}", flush=True)
        return 1
    except ValueError as e:
        # Corrupt JSON. The user has explicitly requested resolution, the JSON
        # is going to be deleted anyway, and aborting would leave anchors with
        # no tool path to clean them up (manual source edits). Proceed loudly.
        print(f"warning: {e}", flush=True)
        print(
            f"resolving {args.id} despite corrupt JSON: stripping anchors and deleting the file.",
            flush=True,
        )
    for path in _find_files_with_anchor(project_root, args.id):
        anchors.remove_anchor(path, args.id)
    findings.delete_finding(project_root, args.id)
    print(f"resolved {args.id}: {args.rationale}", flush=True)
    return 0
