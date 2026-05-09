"""sqa-tool needs-review — files whose blob has changed since last review."""

import argparse
import fnmatch
from pathlib import Path

from sqa_tool import file_status, git_ops
from sqa_tool.config import load_config


def _candidate_files(project_root: Path) -> list[str]:
    config = load_config(project_root)
    if not config.include:
        return []
    tracked = set(git_ops.ls_files(project_root))
    included: set[str] = set()
    for pat in config.include:
        for p in project_root.glob(pat):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(project_root))
            except ValueError:
                continue
            if rel in tracked:
                included.add(rel)
    excluded: set[str] = set()
    for rel in included:
        for pat in config.exclude:
            if fnmatch.fnmatch(rel, pat):
                excluded.add(rel)
                break
    return sorted(included - excluded)


def _changed_files(project_root: Path) -> list[str]:
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
    changed = _changed_files(project_root)
    if args.count:
        print(len(changed))
        return 0
    if args.limit is not None:
        changed = changed[: args.limit]
    for rel in changed:
        print(rel)
    return 0
