"""sqa-tool record-finding — allocate a fresh ID and write the finding JSON."""

import argparse
import fcntl
import os
from pathlib import Path

from sqa_tool import anchors, findings


def run(project_root: Path, args: argparse.Namespace) -> int:
    finding = findings.Finding(
        message=args.message,
        severity=args.severity,
        rationale=args.rationale or "",
        related_files=list(args.related or []),
    )
    finding_id = findings.alloc_id(project_root)
    findings.save_finding(project_root, finding_id, finding)

    if args.anchor:
        target = project_root / args.anchor
        if not anchors.is_commentable(target):
            print(
                f"error: anchor target {args.anchor} is not commentable. "
                f"Insert the anchor into the nearest enclosing .sqa.md instead.",
                flush=True,
            )
            findings.delete_finding(project_root, finding_id)
            return 1
        # Lock-protected insert (sibling subagents may target the same .sqa.md).
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.touch()
        fd = os.open(target, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            anchors.insert_anchor(target, finding_id)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    print(finding_id)
    return 0
