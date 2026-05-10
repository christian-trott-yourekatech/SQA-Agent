"""sqa-tool record-finding — allocate a fresh ID and write the finding JSON."""

import argparse
from pathlib import Path

from sqa_tool import anchors, findings


def run(project_root: Path, args: argparse.Namespace) -> int:
    finding = findings.Finding(
        message=args.message,
        severity=args.severity,
        rationale=args.rationale or "",
        related_files=list(args.related or []),
    )
    # Validate the anchor target BEFORE allocating an ID / writing the finding,
    # so that validation failures don't require a rollback.
    target: Path | None = None
    if args.anchor:
        target = (project_root / args.anchor).resolve()
        try:
            target.relative_to(project_root.resolve())
        except ValueError:
            print(
                f"error: anchor target {args.anchor} resolves outside the project root.",
                flush=True,
            )
            return 1
        if not anchors.is_commentable(target):
            print(
                f"error: anchor target {args.anchor} is not commentable. "
                f"Insert the anchor into the nearest enclosing .sqa.md instead.",
                flush=True,
            )
            return 1

    finding_id = findings.alloc_id(project_root)
    findings.save_finding(project_root, finding_id, finding)

    if target is not None:
        # `insert_anchor` takes its own flock; if any I/O fails, roll back the
        # finding JSON so we don't leave an orphan in .sqa/findings.
        try:
            anchors.insert_anchor(target, finding_id)
        except Exception as e:
            findings.delete_finding(project_root, finding_id)
            print(f"error: failed to insert anchor into {args.anchor}: {e}", flush=True)
            return 1

    print(finding_id)
    return 0
