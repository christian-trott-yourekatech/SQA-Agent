"""sqa-tool mark-reviewed — record a file's current blob hash as last-reviewed."""

import argparse
from pathlib import Path

from sqa_tool import file_status, git_ops


def run(project_root: Path, args: argparse.Namespace) -> int:
    rel = args.path
    target = project_root / rel
    if not target.exists():
        print(f"error: {rel} does not exist", flush=True)
        return 1
    if rel not in set(git_ops.ls_files(project_root)):
        print(
            f"error: {rel} is not tracked by git. mark-reviewed only persists "
            f"hashes for tracked files (untracked paths are filtered out by needs-review).",
            flush=True,
        )
        return 1
    hashes = git_ops.hash_object(project_root, [rel])
    if rel not in hashes:
        print(f"error: could not compute git blob hash for {rel}", flush=True)
        return 1
    file_status.update(project_root, rel, hashes[rel])
    return 0
