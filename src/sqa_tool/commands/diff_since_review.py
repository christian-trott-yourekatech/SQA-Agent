"""sqa-tool diff-since-review — git diff of a file vs its last-reviewed blob."""

import argparse
import sys
from pathlib import Path

from sqa_tool import file_status, git_ops


def run(project_root: Path, args: argparse.Namespace) -> int:
    rel = args.path
    stored = file_status.load(project_root)
    blob = stored.get(rel, "")
    if not blob and not (project_root / rel).exists():
        print(
            f"error: {rel} has no stored blob and does not exist on disk",
            file=sys.stderr,
            flush=True,
        )
        return 1
    diff = git_ops.diff_blob_to_file(project_root, blob, rel)
    if diff:
        print(diff, end="" if diff.endswith("\n") else "\n")
    return 0
