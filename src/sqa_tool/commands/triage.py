"""sqa-tool triage / resolve — finding state transitions."""

import argparse
from pathlib import Path

from sqa_tool import anchors, findings, git_ops


def _find_files_with_anchor(project_root: Path, finding_id: str) -> list[Path]:
    out = []
    for _rel, path in git_ops.walk_tracked_files(project_root):
        try:
            ids = anchors.find_anchors_for_orphan_scan(path)
        except (UnicodeDecodeError, OSError):
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
    return 0


def resolve(project_root: Path, args: argparse.Namespace) -> int:
    """Mark a finding resolved: strip its anchors from source and delete the JSON.

    The `--rationale` argument is accepted (and echoed back as confirmation
    output) but not persisted — under the "git is the audit trail" model, the
    explanation for the fix lives in the user's commit message rather than in
    a JSON field that gets deleted moments later.
    """
    try:
        findings.load_finding(project_root, args.id)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", flush=True)
        return 1
    for path in _find_files_with_anchor(project_root, args.id):
        anchors.remove_anchor(path, args.id)
    findings.delete_finding(project_root, args.id)
    print(f"resolved {args.id}: {args.rationale}", flush=True)
    return 0
