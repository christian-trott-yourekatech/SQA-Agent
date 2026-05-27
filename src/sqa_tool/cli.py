"""sqa-tool CLI entry point and subcommand dispatch."""

import argparse
import sys
from pathlib import Path

from sqa_tool import __version__, paths
from sqa_tool.commands import (
    active_result,
    categories,
    diff_since_review,
    init,
    mark_all_reviewed,
    mark_reviewed,
    needs_review,
    record_finding,
    show,
    start_result,
    triage,
)


def _find_project_root(start: Path) -> tuple[Path, bool] | None:
    """Walk up from `start` looking for the project root.

    Returns ``(root, initialized)`` where ``initialized`` is True iff the
    root was located via the ``.sqa/`` marker; a bare ``.git`` ancestor
    yields ``(root, False)``. At each ancestor level ``.sqa/`` is checked
    before ``.git``, so a co-located ``.sqa/`` always wins.
    """
    current = start.resolve()
    while True:
        if (current / paths.SQA_DIR_NAME).is_dir():
            return current, True
        if (current / paths.GIT_DIR_NAME).exists():
            return current, False
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _project_root_or_die() -> Path:
    """Locate the initialized project root or exit 1 with a helpful message.

    `_find_project_root` deliberately returns ``(root, initialized)`` so
    a future caller with a different policy could accept a bare-``.git``
    ancestor; today every subcommand other than ``init`` requires
    initialization, so this wrapper bakes that single policy in. If a
    second policy ever appears, write its wrapper alongside.
    """
    found = _find_project_root(Path.cwd())
    if found is None:
        print(
            "error: no .sqa/ directory found in any parent — run `sqa-tool init` in a git repo.",
            file=sys.stderr,
        )
        sys.exit(1)
    root, initialized = found
    if not initialized:
        print(
            f"error: {paths.SQA_DIR_NAME}/ not found in {root}. Run `sqa-tool init` first.",
            file=sys.stderr,
        )
        sys.exit(1)
    return root


# These are kept as two named helpers rather than a parameterized factory:
# the names (_nonneg_int, _pos_int) document the bound at every call site,
# and with only two bounds in play the duplication is cheaper than the
# indirection.
def _nonneg_int(value: str) -> int:
    """argparse type for --limit-style flags: accept N >= 0, reject negatives."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def _pos_int(value: str) -> int:
    """argparse type for 1-indexed flags like --line: accept N >= 1, reject 0/negatives."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from None
    if n <= 0:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def _add_from_arg(p: argparse.ArgumentParser) -> None:
    """Attach the standard ``--from`` flag to a read-side subparser."""
    p.add_argument(
        "--from",
        dest="from_",
        default=None,
        help="Read from this result file instead of the active one",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sqa-tool",
        description="Deterministic CLI for the SQA review system.",
    )
    p.add_argument("--version", action="version", version=f"sqa-tool {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Scaffold .sqa/ in the current project")

    sr = sub.add_parser(
        "start-result",
        help="Begin a new review session (creates .sqa/result_<timestamp>.json)",
    )
    sr.add_argument(
        "--force",
        action="store_true",
        help=(
            "Start a new session even if the previous one has open findings. "
            "Use only for legitimate fresh-session starts after an abandoned pass; "
            "subagents should never need this."
        ),
    )
    sub.add_parser("active-result", help="Print the path of the most recent result file")
    sub.add_parser("categories", help="Print the project's review-category list")

    rf = sub.add_parser("record-finding", help="Record a new finding and return its ID")
    rf.add_argument("--message", required=True, help="Finding message (required)")
    rf.add_argument(
        "--severity",
        choices=["info", "warning", "error"],
        default="info",
        help="Finding severity level (default: info)",
    )
    rf.add_argument(
        "--file",
        default=None,
        help="Project-relative path the finding is about. Omit for project-wide findings.",
    )
    rf.add_argument("--line", type=_pos_int, default=None, help="Line number in --file (optional)")
    rf.add_argument(
        "--quoted-text",
        dest="quoted_text",
        default=None,
        help="Short excerpt of the offending code (optional, helps the resolver disambiguate)",
    )
    rf.add_argument("--category", default="", help="Review category (see `sqa-tool categories`)")
    rf.add_argument(
        "--related",
        action="append",
        help="Other files the finding concerns (may repeat)",
    )
    # Rationale is optional here (a reviewer may not yet have a fix in mind
    # when recording) but required for `triage` and `resolve`, where a
    # decision is being captured and its justification must be on record.
    rf.add_argument(
        "--rationale",
        default="",
        help="Initial rationale (default: empty, may be filled in by later triage)",
    )
    rf.add_argument(
        "--force",
        action="store_true",
        help=(
            "Bypass the post-resolve safety guard, which normally blocks new "
            "findings once the active result has any resolved entries (review "
            "and resolve are meant to be separate phases). Only legitimate "
            "for deliberate reviewer add-ons during a resolve pass."
        ),
    )

    sf = sub.add_parser("show-finding", help="Print one finding as JSON")
    sf.add_argument("id", type=int)
    _add_from_arg(sf)

    lf = sub.add_parser("list-findings", help="List findings as a JSON array")
    lf.add_argument("--triage", choices=["auto", "interactive", "ignore", "untriaged"])
    lf.add_argument("--status", choices=["open", "resolved"])
    lf.add_argument(
        "--count",
        action="store_true",
        help="Print just the integer count (ignores --limit)",
    )
    lf.add_argument("--limit", type=_nonneg_int, help="Print at most N findings")
    _add_from_arg(lf)

    st = sub.add_parser("status", help="Counts and breakdowns of findings")
    _add_from_arg(st)

    nr = sub.add_parser("needs-review", help="List files whose blob has changed since last review")
    nr.add_argument(
        "--count",
        action="store_true",
        help="Print just the integer count of changed files (ignores --limit)",
    )
    nr.add_argument("--limit", type=_nonneg_int, help="Print at most N files")

    mr = sub.add_parser("mark-reviewed", help="Record a file's current blob hash")
    mr.add_argument("path")

    sub.add_parser(
        "mark-all-reviewed",
        help="Record current blob hashes for every file in the candidate set",
    )

    ff = sub.add_parser(
        "findings-for-file",
        help="Findings whose `file` or `related` list matches the given path",
    )
    ff.add_argument("path")
    _add_from_arg(ff)

    tr = sub.add_parser("triage", help="Set triage decision and rationale on a finding")
    tr.add_argument("id", type=int)
    tr.add_argument("decision", choices=["auto", "interactive", "ignore"])
    tr.add_argument("--rationale", required=True)

    rs = sub.add_parser("resolve", help="Flip a finding's status to resolved")
    rs.add_argument("id", type=int)
    rs.add_argument("--rationale", required=True)

    ds = sub.add_parser(
        "diff-since-review", help="Print git diff of a file vs its last-reviewed blob"
    )
    ds.add_argument("path")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        # init bootstraps the project, so it can't go through the standard
        # project-root + initialization preflight below. Its own preconditions
        # (git repo, at least one commit) live in init.run().
        return init.run(Path.cwd())

    project_root = _project_root_or_die()

    # Dispatch for all non-init commands.
    #
    # Convention: most subcommands live in their own file under commands/
    # exposing `run(project_root, args)`. Two exceptions group handlers that
    # share non-trivial scaffolding: show.py (the read-side helpers `_load`
    # and `_filter`) and triage.py (the shared `_mutate_active_finding`
    # lock-then-mutate path for the state machine). New subcommands should
    # default to the one-file-per-command form; only group when shared
    # helpers would be substantial.
    dispatch = {
        "start-result": lambda: start_result.run(project_root, args),
        "active-result": lambda: active_result.run(project_root, args),
        "categories": lambda: categories.run(project_root, args),
        "record-finding": lambda: record_finding.run(project_root, args),
        "show-finding": lambda: show.show(project_root, args),
        "list-findings": lambda: show.list_(project_root, args),
        "status": lambda: show.status(project_root, args),
        "needs-review": lambda: needs_review.run(project_root, args),
        "mark-reviewed": lambda: mark_reviewed.run(project_root, args),
        "mark-all-reviewed": lambda: mark_all_reviewed.run(project_root, args),
        "findings-for-file": lambda: show.for_file(project_root, args),
        "triage": lambda: triage.triage(project_root, args),
        "resolve": lambda: triage.resolve(project_root, args),
        "diff-since-review": lambda: diff_since_review.run(project_root, args),
    }
    return dispatch[args.command]()


if __name__ == "__main__":
    sys.exit(main())
