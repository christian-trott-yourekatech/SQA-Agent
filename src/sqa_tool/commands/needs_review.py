"""sqa-tool needs-review — files whose blob has changed since last review."""

import argparse
import sys
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
            # Path.glob() only yields paths beneath project_root, so
            # relative_to() cannot raise ValueError here.
            rel = str(p.relative_to(project_root))
            if rel in tracked:
                out.add(rel)
    return out


# Note: the stderr warnings emitted below are intentionally surfaced from
# every caller, including show.changed_files() invoked by `sqa-tool status`,
# not just the needs-review CLI path. Surfacing a misconfigured
# .sqa/config.toml (empty include list, non-matching globs) the first time
# the user runs any command that consults the include list helps catch typos
# and fresh-clone mismatches early. The occasional duplicate warning across
# two commands in the same shell is preferable to silently hiding the same
# misconfiguration that needs-review would otherwise flag.
def _candidate_files(project_root: Path) -> list[str]:
    config = load_config(project_root)
    if not config.include:
        # Distinguish "nothing configured" from "nothing changed". The
        # default config written by `sqa-tool init` ships include = [], so a
        # fresh project would otherwise silently report no work to do.
        print(
            "warning: config.include is empty in .sqa/config.toml — no files "
            "will be reviewed. Add glob patterns under [files].include to enable review.",
            file=sys.stderr,
        )
        return []
    tracked = set(git_ops.ls_files(project_root))
    included = _glob_to_relpaths(project_root, config.include, tracked)
    excluded = _glob_to_relpaths(project_root, config.exclude, tracked)
    result = sorted(included - excluded)
    if not result:
        # Distinguish "globs match no tracked files" from "no changes since
        # last review". Without this, a typo in an include pattern (or a
        # freshly cloned tree where the configured globs don't match yet)
        # would silently surface as "Review pass complete" via the --count
        # hint path.
        print(
            "warning: config.include patterns in .sqa/config.toml match no "
            "tracked files. Check for typos in glob patterns or verify the "
            "patterns apply to this tree.",
            file=sys.stderr,
        )
    return result


def changed_files(project_root: Path) -> list[str]:
    """Return tracked, included candidate files whose current git blob hash
    differs from the baseline recorded in file_status.

    Deleted files are not reported here. The set is computed from the
    intersection of (configured globs) ∩ (currently-tracked files), so paths
    that vanished from the working tree or fell out of include/exclude scope
    drop out naturally without explicit reconciliation.
    """
    candidates = _candidate_files(project_root)
    if not candidates:
        return []
    current = git_ops.hash_object(project_root, candidates)
    stored = file_status.load(project_root)
    out = []
    for rel in candidates:
        # Guard against a TOCTOU race: candidates came from git ls_files()
        # in _candidate_files(), but hash_object() only returns entries for
        # paths that still exist on disk. A file deleted between those two
        # calls will be absent from `current` and is skipped here.
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
        # Next-step hint to stderr (stdout stays pure for `$(…)` capture).
        # Keeps a loop agent oriented across many batches without it needing
        # to re-read the skill markdown each iteration.
        n = len(changed)
        if n > 0:
            print(
                f"hint: {n} files remain — use --limit=N to fetch a batch.",
                file=sys.stderr,
            )
        else:
            print(
                "hint: 0 files remain. Review pass complete; run `sqa-tool status` "
                "for the summary.",
                file=sys.stderr,
            )
        return 0
    if args.limit is not None:
        changed = changed[: args.limit]
    for rel in changed:
        print(rel)
    return 0
