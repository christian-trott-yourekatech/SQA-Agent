"""sqa-tool triage / resolve — finding state transitions."""

import argparse
from pathlib import Path

from sqa_tool import anchors, findings, git_ops


def _find_files_with_anchor(project_root: Path, finding_id: str) -> list[Path]:
    out = []
    for _rel, path in git_ops.walk_tracked_files(project_root):
        try:
            ids = anchors.find_anchors_in_file(path)
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
    try:
        f = findings.load_finding(project_root, args.id)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", flush=True)
        return 1
    f.status = "resolved"
    f.rationale = args.rationale
    findings.save_finding(project_root, args.id, f)
    # Remove anchors from any source/.sqa.md files that reference this ID.
    for path in _find_files_with_anchor(project_root, args.id):
        anchors.remove_anchor(path, args.id)
    return 0
