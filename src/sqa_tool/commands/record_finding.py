"""sqa-tool record-finding — append a new finding to the active result file.

Writes to ``.sqa/result_<timestamp>.json`` (the most recent one). Refuses to
run if no active result exists (the user forgot to ``start-result``) or if
the active result already contains any resolved findings (a likely sign the
user forgot to start a new result for a fresh review). The second guard can
be bypassed with ``--force``.
"""

import argparse
import sys
from pathlib import Path

from sqa_tool import paths
from sqa_tool.config import load_config
from sqa_tool.result_file import (
    Finding,
    active_result_or_exit_message,
    add_finding,
    has_any_resolved,
    with_locked_result,
)


def run(project_root: Path, args: argparse.Namespace) -> int:
    sqa_dir = paths.sqa_dir(project_root)
    result_path = active_result_or_exit_message(sqa_dir)
    if result_path is None:
        return 1

    # --line / --quoted-text only meaningful with --file. Reject the
    # nonsensical combinations rather than silently storing values that will
    # never be used. Run hard validation before the soft category warning
    # below so a failed invocation doesn't also emit a spurious category
    # warning to stderr.
    #
    # quoted_text uses truthiness (not "is not None") to match the
    # normalization below where `args.quoted_text or None` collapses empty
    # string to None — both checks share the semantic that empty
    # quoted_text means "not provided", while `line` is a typed int|None
    # so explicit `is not None` is appropriate there.
    if (args.line is not None or args.quoted_text) and not args.file:
        print(
            "error: --line / --quoted-text require --file (project-wide "
            "findings can't anchor to a specific line).",
            file=sys.stderr,
        )
        return 1

    # Soft category validation — warn but accept. Keeps the agent unblocked
    # if it picks a near-miss name; misuse shows up in `sqa-tool status` later.
    # Also warn when --category is omitted in a project that has configured
    # categories: a silently empty category is almost always a forgotten flag,
    # not an intentional "uncategorized" finding.
    cfg = load_config(project_root)
    if cfg.categories:
        if not args.category:
            print(
                f"warning: --category not provided. Configured categories: "
                f"{', '.join(cfg.categories)}. Recording with empty category.",
                file=sys.stderr,
            )
        elif args.category not in cfg.categories:
            print(
                f"warning: category {args.category!r} not in configured list "
                f"({', '.join(cfg.categories)}). Recording anyway.",
                file=sys.stderr,
            )

    finding = Finding(
        message=args.message,
        file=args.file,
        line=args.line,
        quoted_text=args.quoted_text or None,
        category=args.category,
        severity=args.severity,
        rationale=args.rationale,
        related=list(args.related or []),
    )

    with with_locked_result(result_path) as (_, findings):
        # Safety guard. Once any finding in this result is resolved, the
        # review-record phase of the session is logically over — appending
        # more findings here is almost certainly a "forgot to start-result"
        # mistake. --force is the escape hatch.
        if has_any_resolved(findings) and not args.force:
            print(
                f"error: active result {result_path.name} already has resolved "
                "findings; new findings would mix into a post-resolve state. "
                "Run `sqa-tool start-result` for a fresh session, or pass "
                "--force to override.",
                file=sys.stderr,
            )
            return 1
        new_id = add_finding(findings, finding)

    print(new_id)
    return 0
