"""sqa-tool gc — prune resolved findings older than a duration window."""

import argparse
import re
import time
from pathlib import Path

from sqa_tool import findings, paths

_DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(s: str) -> float:
    """Parse a duration string like '30d', '24h', '1w'. Returns seconds."""
    m = _DURATION_RE.match(s.strip())
    if not m:
        raise ValueError(f"Invalid duration: {s!r}. Expected e.g. 30d, 24h, 1w.")
    value = int(m.group(1))
    unit = m.group(2)
    return value * _UNIT_SECONDS[unit]


def run(project_root: Path, args: argparse.Namespace) -> int:
    cutoff: float | None = None
    if args.older_than:
        try:
            window = parse_duration(args.older_than)
        except ValueError as e:
            print(f"error: {e}", flush=True)
            return 1
        cutoff = time.time() - window

    deleted = []
    for fid in findings.list_finding_ids(project_root):
        try:
            f = findings.load_finding(project_root, fid)
        except (FileNotFoundError, ValueError):
            continue
        if f.status != "resolved":
            continue
        path = paths.finding_path(project_root, fid)
        if cutoff is not None:
            mtime = path.stat().st_mtime
            if mtime > cutoff:
                continue
        path.unlink()
        deleted.append(fid)

    print(
        f"deleted {len(deleted)} resolved finding(s): {', '.join(deleted) if deleted else 'none'}"
    )
    return 0
