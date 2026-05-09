"""sqa-tool findings-for-file — scope-aware finding lookup for a single file."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from sqa_tool import scope


def run(project_root: Path, args: argparse.Namespace) -> int:
    items = scope.findings_for_file(project_root, args.path)
    print(json.dumps([{"id": fid, **asdict(f)} for fid, f in items], indent=2))
    return 0
