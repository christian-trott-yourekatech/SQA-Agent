"""sqa-tool show-finding / list-findings / status."""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from sqa_tool import findings
from sqa_tool.commands.needs_review import changed_files


def show(project_root: Path, args: argparse.Namespace) -> int:
    try:
        f = findings.load_finding(project_root, args.id)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr, flush=True)
        return 1
    payload = {"id": args.id, **asdict(f)}
    print(json.dumps(payload, indent=2))
    return 0


def _filter(
    items: list[tuple[str, findings.Finding]],
    triage: str | None,
    status: str | None,
) -> list[tuple[str, findings.Finding]]:
    out = []
    for fid, f in items:
        if triage is not None:
            if triage == "untriaged":
                if f.triage is not None:
                    continue
            elif f.triage != triage:
                continue
        if status is not None and f.status != status:
            continue
        out.append((fid, f))
    return out


def _load_all(
    project_root: Path,
) -> tuple[list[tuple[str, findings.Finding]], int]:
    """Load every finding; warn to stderr on failures; return (items, load_errors)."""
    items: list[tuple[str, findings.Finding]] = []
    load_errors = 0
    for fid in findings.list_finding_ids(project_root):
        try:
            items.append((fid, findings.load_finding(project_root, fid)))
        except (FileNotFoundError, ValueError) as e:
            print(f"warning: failed to load finding {fid}: {e}", file=sys.stderr, flush=True)
            load_errors += 1
    return items, load_errors


def list_(project_root: Path, args: argparse.Namespace) -> int:
    items, load_errors = _load_all(project_root)
    items = _filter(items, args.triage, args.status)
    if args.count:
        print(len(items))
        return 1 if load_errors > 0 else 0
    if args.limit is not None:
        items = items[: args.limit]
    print(json.dumps([{"id": fid, **asdict(f)} for fid, f in items], indent=2))
    return 1 if load_errors > 0 else 0


def status(project_root: Path, args: argparse.Namespace) -> int:
    items, load_errors = _load_all(project_root)
    by_triage: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    for _fid, f in items:
        triage_key = f.triage if f.triage is not None else "untriaged"
        by_triage[triage_key] += 1
        by_severity[f.severity] += 1
        by_status[f.status] += 1

    needs_review_count: int | None
    try:
        needs_review_count = len(changed_files(project_root))
    except Exception as e:
        # If config is missing or git ops fail, surface as null rather than
        # blowing up the whole status output.
        print(
            f"warning: could not compute needs-review count: {e}",
            file=sys.stderr,
            flush=True,
        )
        needs_review_count = None

    payload = {
        # `total` is the count of successfully-loaded findings, so it always
        # equals sum(by_triage) == sum(by_severity) == sum(by_status). Items
        # that failed to load are surfaced separately as `load_errors`.
        "total": len(items),
        "by_triage": dict(by_triage),
        "by_severity": dict(by_severity),
        "by_status": dict(by_status),
        "load_errors": load_errors,
        "needs_review": needs_review_count,
    }
    print(json.dumps(payload, indent=2))
    return 0
