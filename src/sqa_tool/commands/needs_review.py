"""sqa-tool needs-review — files whose blob has changed since last review."""

import argparse
from pathlib import Path

from sqa_tool import file_status, git_ops
from sqa_tool.config import load_config


def _glob_to_relpaths(project_root: Path, patterns: list[str], tracked: set[str]) -> set[str]:
    """Resolve patterns via Path.glob and return the subset that matches tracked files."""
    out: set[str] = set()
    for pat in patterns:
        for p in project_root.glob(pat):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(project_root))
            except ValueError:
                continue
            if rel in tracked:
                out.add(rel)
    return out


def _candidate_files(project_root: Path) -> list[str]:
    config = load_config(project_root)
    if not config.include:
        return []
    tracked = set(git_ops.ls_files(project_root))
    included = _glob_to_relpaths(project_root, config.include, tracked)
    excluded = _glob_to_relpaths(project_root, config.exclude, tracked)
    return sorted(included - excluded)


def changed_files(project_root: Path) -> list[str]:
    """Return tracked, included candidate files whose current git blob hash
    differs from the baseline recorded in file_status.

    Deleted files are not reported here; orphan handling (files that vanished
    from the working tree or fell out of include/exclude scope) is delegated
    to the orphans command.
    """
    candidates = _candidate_files(project_root)
    if not candidates:
        return []
    current = git_ops.hash_object(project_root, candidates)
    stored = file_status.load(project_root)
    out = []
    for rel in candidates:
        cur_hash = current.get(rel)
        if cur_hash is None:
            continue
        if stored.get(rel) != cur_hash:
            out.append(rel)
    return out


def run(project_root: Path, args: argparse.Namespace) -> int:
    changed = changed_files(project_root)
    if args.count:
        print(len(changed))
        return 0
    if args.limit is not None:
        changed = changed[: args.limit]
    for rel in changed:
        print(rel)
    return 0
