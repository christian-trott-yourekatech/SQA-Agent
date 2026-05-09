"""sqa-tool show-finding / list-findings / status."""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from sqa_tool import findings


def show(project_root: Path, args: argparse.Namespace) -> int:
    try:
        f = findings.load_finding(project_root, args.id)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", flush=True)
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


def list_(project_root: Path, args: argparse.Namespace) -> int:
    ids = findings.list_finding_ids(project_root)
    items: list[tuple[str, findings.Finding]] = []
    for fid in ids:
        try:
            items.append((fid, findings.load_finding(project_root, fid)))
        except (FileNotFoundError, ValueError) as e:
            print(f"warning: failed to load finding {fid}: {e}", file=sys.stderr, flush=True)
            continue
    items = _filter(items, args.triage, args.status)
    if args.count:
        print(len(items))
        return 0
    if args.limit is not None:
        items = items[: args.limit]
    print(json.dumps([{"id": fid, **asdict(f)} for fid, f in items], indent=2))
    return 0


def status(project_root: Path, args: argparse.Namespace) -> int:
    ids = findings.list_finding_ids(project_root)
    by_triage: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    load_errors = 0
    for fid in ids:
        try:
            f = findings.load_finding(project_root, fid)
        except (FileNotFoundError, ValueError) as e:
            print(f"warning: failed to load finding {fid}: {e}", file=sys.stderr, flush=True)
            load_errors += 1
            continue
        triage_key = f.triage if f.triage is not None else "untriaged"
        by_triage[triage_key] += 1
        by_severity[f.severity] += 1
        by_status[f.status] += 1
    payload = {
        "total": len(ids),
        "by_triage": dict(by_triage),
        "by_severity": dict(by_severity),
        "by_status": dict(by_status),
        "load_errors": load_errors,
    }
    print(json.dumps(payload, indent=2))
    return 0
