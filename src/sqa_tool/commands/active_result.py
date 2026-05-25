"""sqa-tool active-result — print the path of the most recent result file.

Exits non-zero if no result file exists yet (the typical "you forgot to run
start-result" case). Callers that want to silently handle the no-result
case can redirect stderr and check the exit code.
"""

import argparse
import sys
from pathlib import Path

from sqa_tool import paths
from sqa_tool.result_file import active_result_path


def run(project_root: Path, args: argparse.Namespace) -> int:
    sqa_dir = paths.sqa_dir(project_root)
    path = active_result_path(sqa_dir)
    if path is None:
        print(
            "error: no result file in .sqa/. Run `sqa-tool start-result` to begin a session.",
            file=sys.stderr,
        )
        return 1
    print(path)
    return 0
