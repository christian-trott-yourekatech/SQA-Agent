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
        target = (project_root / args.anchor).resolve()
        try:
            target.relative_to(project_root.resolve())
        except ValueError:
            print(
                f"error: anchor target {args.anchor} resolves outside the project root.",
                flush=True,
            )
            findings.delete_finding(project_root, finding_id)
            return 1
        if not anchors.is_commentable(target):
            print(
                f"error: anchor target {args.anchor} is not commentable. "
                f"Insert the anchor into the nearest enclosing .sqa.md instead.",
                flush=True,
            )
            findings.delete_finding(project_root, finding_id)
            return 1
        # Lock-protected insert (sibling subagents may target the same .sqa.md).
        # If anything goes wrong, roll back the finding JSON so we don't leave
        # an orphan in .sqa/findings.
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.touch()
        fd = os.open(target, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                anchors.insert_anchor(target, finding_id)
            except Exception as e:
                findings.delete_finding(project_root, finding_id)
                print(f"error: failed to insert anchor into {args.anchor}: {e}", flush=True)
                return 1
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    print(finding_id)
    return 0
