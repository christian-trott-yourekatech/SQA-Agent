"""sqa-tool triage / resolve / reopen — finding state transitions."""

import argparse
from pathlib import Path

from sqa_tool import anchors, findings


def _walk_files(project_root: Path):
    """Yield every project-relative path that may contain anchors.

    For now, iterate git-tracked files; this is acceptable since anchors live
    only in tracked content. (Re-importing here to avoid a circular import at
    module load time.)
    """
    from sqa_tool import git_ops

    if not git_ops.is_repo(project_root):
        return []
    return git_ops.ls_files(project_root)


def _find_files_with_anchor(project_root: Path, finding_id: str) -> list[Path]:
    out = []
    for rel in _walk_files(project_root):
        path = project_root / rel
        if not path.is_file():
            continue
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


def reopen(project_root: Path, args: argparse.Namespace) -> int:
    try:
        f = findings.load_finding(project_root, args.id)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", flush=True)
        return 1
    f.status = "open"
    f.rationale = args.rationale
    findings.save_finding(project_root, args.id, f)
    return 0
