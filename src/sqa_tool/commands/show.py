"""sqa-tool show-finding / list-findings / status / findings-for-file — read-side commands.

All four commands read from the **active** result file by default; the
``--from`` flag points at a specific historical result. These commands
never write — they only read. (The rejection of ``--from`` on mutating
commands like triage and record-finding is enforced in those modules,
not here.)

When no active result exists, the read commands return empty/zero output
rather than error — this lets a skill's loop guard (`list-findings --count`)
sensibly answer "nothing to do" before any review has run.
"""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from sqa_tool import paths
from sqa_tool.commands.needs_review import changed_files
from sqa_tool.git_ops import GitError
from sqa_tool.result_file import (
    Finding,
    active_result_path,
    findings_for_file,
    load_result,
    select_result,
)

# --- Shared load path ------------------------------------------------------


def _load(project_root: Path, from_value: str | None) -> tuple[list[Finding], Path | None]:
    """Load findings from the chosen result file.

    Returns (findings, path). When ``from_value`` is None and no active
    result exists, returns ([], None) — letting the caller answer
    "zero findings" rather than erroring out (this is the documented
    behaviour for list-findings and status). When ``from_value`` is set
    and the path doesn't exist, that *is* an error (user typed a name
    that doesn't exist) and ``select_result`` raises FileNotFoundError.
    """
    sqa = paths.sqa_dir(project_root)
    if from_value is None and active_result_path(sqa) is None:
        return [], None
    # Delegate all "resolve --from or fall back to active, raise on bad
    # path" logic to select_result so the --from semantics live in one
    # place (result_file.select_result).
    path = select_result(sqa, from_value)
    return load_result(path), path


def _load_or_exit(project_root: Path, from_value: str | None) -> tuple[list[Finding], Path | None]:
    """Call _load, but on FileNotFoundError print the error and sys.exit(1).

    Tolerates "no active result" (returns ([], None)) for list-findings
    and status, which treat that as "zero findings" per the module
    docstring. Handlers that need a result file (show-finding,
    findings-for-file) should call :func:`_load_required_or_exit`.
    """
    try:
        return _load(project_root, from_value)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def _load_required_or_exit(
    project_root: Path, from_value: str | None
) -> tuple[list[Finding], Path]:
    """Like :func:`_load_or_exit`, but errors out if no result file exists.

    show-finding and findings-for-file have no meaningful "zero" output
    when there's no result file at all (an empty array would be
    indistinguishable from "result file exists, nothing matched").
    """
    items, path = _load_or_exit(project_root, from_value)
    if path is None:
        print("error: no active result file", file=sys.stderr)
        sys.exit(1)
    return items, path


# --- show-finding ----------------------------------------------------------


def show(project_root: Path, args: argparse.Namespace) -> int:
    # args.id is already an int (argparse `type=int` on the `show-finding`
    # positional in cli.py); no manual parsing or error-handling needed here.
    finding_id = args.id
    # _load_required_or_exit distinguishes "no active result file" from
    # "no finding with that ID" — otherwise a fresh project with zero
    # results would falsely report the ID as missing.
    items, _ = _load_required_or_exit(project_root, args.from_)
    for f in items:
        if f.id == finding_id:
            print(json.dumps(asdict(f), indent=2))
            return 0
    print(f"error: no finding with id {finding_id}", file=sys.stderr)
    return 1


# --- list-findings ---------------------------------------------------------


def _filter(items: list[Finding], triage: str | None, status: str | None) -> list[Finding]:
    out = []
    for f in items:
        if triage is not None:
            if triage == "untriaged":
                if f.triage is not None:
                    continue
            elif f.triage != triage:
                continue
        if status is not None and f.status != status:
            continue
        out.append(f)
    return out


def list_(project_root: Path, args: argparse.Namespace) -> int:
    items, _ = _load_or_exit(project_root, args.from_)
    items = _filter(items, args.triage, args.status)
    if args.count:
        print(len(items))
        _print_count_hint(args, len(items))
        return 0
    if args.limit is not None:
        items = items[: args.limit]
    print(json.dumps([asdict(f) for f in items], indent=2))
    return 0


# Maps a (triage, status) gate query to (noun_phrase, phase_name) so the
# hint message can be table-driven; adding a new gate query is one tuple
# entry. Keys must match what list-findings callers pass in; phase names
# match the workflow vocabulary the skill markdown uses.
_COUNT_HINT_PHASES: dict[tuple[str | None, str | None], tuple[str, str]] = {
    ("untriaged", None): ("untriaged findings", "triage"),
    ("auto", "open"): ("auto findings open", "auto-resolve"),
    ("interactive", "open"): ("interactive findings open", "interactive-resolve"),
}


def _print_count_hint(args: argparse.Namespace, count: int) -> None:
    """Emit a phase-identification hint to stderr for known gate queries.

    The hints confirm which phase the count belongs to (triage / auto-resolve /
    interactive-resolve) using CLI vocabulary only. Workflow rules (parallelism,
    dispatch shape, which subagent to spawn) live in the skill markdown, not
    here.
    """
    entry = _COUNT_HINT_PHASES.get((args.triage, args.status))
    if entry is None:
        return
    noun_phrase, phase = entry
    if count > 0:
        msg = f"hint: {count} {noun_phrase} — advance to the {phase} phase."
    else:
        msg = f"hint: 0 {noun_phrase} — {phase} phase complete."
    print(msg, file=sys.stderr)


# --- status ----------------------------------------------------------------


def status(project_root: Path, args: argparse.Namespace) -> int:
    items, result_path = _load_or_exit(project_root, args.from_)

    by_triage: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    for f in items:
        triage_key = f.triage if f.triage is not None else "untriaged"
        by_triage[triage_key] += 1
        by_severity[f.severity] += 1
        by_status[f.status] += 1

    # Only compute needs-review against the active session — historical
    # result files don't have a meaningful "files still pending" companion.
    needs_review_count: int | None = None
    if args.from_ is None:
        # Narrow to expected failure modes: GitError (git missing, repo
        # corruption, or git command failure from git_ops), OSError (file
        # I/O / file_status read), and RuntimeError (corrupt file_status
        # raised by file_status._parse_status). Anything else is a genuine
        # bug we want to surface rather than silently bury.
        try:
            needs_review_count = len(changed_files(project_root))
        except (GitError, OSError, RuntimeError) as e:
            print(
                f"warning: could not compute needs-review count: {e}",
                file=sys.stderr,
            )

    payload = {
        "result_file": str(result_path) if result_path else None,
        "total": len(items),
        "by_triage": dict(by_triage),
        "by_severity": dict(by_severity),
        "by_status": dict(by_status),
        "needs_review": needs_review_count,
    }
    print(json.dumps(payload, indent=2))
    return 0


# --- findings-for-file -----------------------------------------------------


def for_file(project_root: Path, args: argparse.Namespace) -> int:
    # An empty JSON array here would be misleading when there's no result
    # file at all — distinguish that from "result file exists, no findings
    # match this path." _load_required_or_exit enforces that.
    items, _ = _load_required_or_exit(project_root, args.from_)
    matched = findings_for_file(items, args.path)
    print(json.dumps([asdict(f) for f in matched], indent=2))
    return 0
