"""sqa-tool CLI entry point and subcommand dispatch."""

import argparse
import sys
from pathlib import Path

from sqa_tool import __version__, git_ops, paths
from sqa_tool.commands import (
    diff_since_review,
    findings_for_file,
    init,
    mark_reviewed,
    needs_review,
    orphans,
    record_finding,
    show,
    triage,
)


def _find_project_root(start: Path) -> Path | None:
    """Walk up from `start` looking for a directory that contains .sqa/ or is a git root."""
    current = start.resolve()
    while True:
        if (current / paths.SQA_DIR_NAME).is_dir():
            return current
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _project_root_or_die() -> Path:
    root = _find_project_root(Path.cwd())
    if root is None:
        print(
            "error: not inside a project (no .sqa/ or .git/ found in any parent)",
            file=sys.stderr,
        )
        sys.exit(1)
    return root


def _require_initialized(root: Path) -> None:
    if not paths.sqa_dir(root).is_dir():
        print(
            f"error: {paths.SQA_DIR_NAME}/ not found in {root}. Run `sqa-tool init` first.",
            file=sys.stderr,
        )
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sqa-tool",
        description="Deterministic CLI for the SQA review system.",
    )
    p.add_argument("--version", action="version", version=f"sqa-tool {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Scaffold .sqa/ in the current project")

    rf = sub.add_parser("record-finding", help="Record a new finding and return its ID")
    rf.add_argument("--message", required=True)
    rf.add_argument("--severity", choices=["info", "warning", "error"], default="info")
    rf.add_argument("--anchor", help="File to insert an anchor comment into (under lock)")
    rf.add_argument("--related", action="append", help="File the finding is about (may repeat)")
    rf.add_argument("--rationale", default="", help="Initial rationale")

    sf = sub.add_parser("show-finding", help="Print one finding as JSON")
    sf.add_argument("id")

    lf = sub.add_parser("list-findings", help="List findings as a JSON array")
    lf.add_argument("--triage", choices=["auto", "interactive", "ignore", "untriaged"])
    lf.add_argument("--status", choices=["open", "resolved"])
    lf.add_argument("--count", action="store_true", help="Print just the integer count")
    lf.add_argument("--limit", type=int, help="Print at most N findings")

    sub.add_parser("status", help="Counts and breakdowns of findings")

    nr = sub.add_parser("needs-review", help="List files whose blob has changed since last review")
    nr.add_argument("--count", action="store_true")
    nr.add_argument("--limit", type=int)

    mr = sub.add_parser("mark-reviewed", help="Record a file's current blob hash")
    mr.add_argument("path")

    ff = sub.add_parser(
        "findings-for-file",
        help="Findings in scope for a file (anchor in file or matching ancestor scope)",
    )
    ff.add_argument("path")

    tr = sub.add_parser("triage", help="Set triage decision and rationale on a finding")
    tr.add_argument("id")
    tr.add_argument("decision", choices=["auto", "interactive", "ignore"])
    tr.add_argument("--rationale", required=True)

    rs = sub.add_parser("resolve", help="Mark a finding resolved and remove its anchors")
    rs.add_argument("id")
    rs.add_argument("--rationale", required=True)

    ds = sub.add_parser(
        "diff-since-review", help="Print git diff of a file vs its last-reviewed blob"
    )
    ds.add_argument("path")

    sub.add_parser(
        "orphans",
        help="Detect and auto-fix anchor/finding inconsistencies",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        # init creates the project, doesn't require existing state, but does
        # require a sensible cwd (a git repo with at least one commit, since
        # the reviewer's change-detection relies on `git ls-files` and blob
        # hashing — neither produces useful output before the first commit).
        cwd = Path.cwd()
        if not git_ops.is_repo(cwd):
            print(
                "error: sqa-tool requires a git repository. Run `git init` first, "
                "stage and commit your initial files, then try again.",
                file=sys.stderr,
            )
            return 1
        if not git_ops.has_commits(cwd):
            print(
                "error: this git repository has no commits yet. The reviewer needs "
                "at least one commit because change detection works against tracked "
                "files. Run `git add .` and `git commit -m 'initial'`, then try again.",
                file=sys.stderr,
            )
            return 1
        return init.run(cwd)

    project_root = _project_root_or_die()
    _require_initialized(project_root)

    dispatch = {
        "record-finding": lambda: record_finding.run(project_root, args),
        "show-finding": lambda: show.show(project_root, args),
        "list-findings": lambda: show.list_(project_root, args),
        "status": lambda: show.status(project_root, args),
        "needs-review": lambda: needs_review.run(project_root, args),
        "mark-reviewed": lambda: mark_reviewed.run(project_root, args),
        "findings-for-file": lambda: findings_for_file.run(project_root, args),
        "triage": lambda: triage.triage(project_root, args),
        "resolve": lambda: triage.resolve(project_root, args),
        "diff-since-review": lambda: diff_since_review.run(project_root, args),
        "orphans": lambda: orphans.run(project_root, args),
    }
    return dispatch[args.command]()


if __name__ == "__main__":
    sys.exit(main())
