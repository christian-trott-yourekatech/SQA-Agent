"""sqa-tool start-result — create a fresh result file for this review session.

Output (stdout, one item per line):
    <path-to-new-result-file>
    Categories: <category1>, <category2>, ...

The path-first format keeps the value easy to capture with shell tools
(`RESULT=$(sqa-tool start-result | head -1)`); the categories line is a
convenience for the calling skill agent so it can echo the review's scope
back to the user without a separate `categories` call.

Refuses (exit 1) if the previous session's result file has any open
findings — the typical mid-session "subagent accidentally rotated the
active result" footgun. Pass ``--force`` to start a new session anyway
(legitimate when the prior session was abandoned mid-flight).
"""

import argparse
import sys
from pathlib import Path

from sqa_tool import paths
from sqa_tool.config import load_config
from sqa_tool.result_file import UnresolvedFindingsError, start_result


def run(project_root: Path, args: argparse.Namespace) -> int:
    cfg = load_config(project_root)
    sqa_dir = paths.sqa_dir(project_root)
    try:
        path = start_result(sqa_dir, force=args.force)
    except UnresolvedFindingsError as e:
        print(
            f"error: {e}\n"
            "If this is the parent skill starting a fresh review pass after "
            "an abandoned session, re-run with --force. If this is a subagent "
            "calling start-result mid-session, stop — only the parent skill "
            "should ever start a new result file.",
            file=sys.stderr,
        )
        return 1
    except FileExistsError as e:
        # Same-second collision: only realistically hit by back-to-back
        # automated invocations. Surface a friendly hint rather than a
        # Python traceback; the natural recovery is "wait a second."
        print(
            f"error: {e}. A previous `start-result` ran within the same "
            "second; wait a moment and retry.",
            file=sys.stderr,
        )
        return 1
    print(path)
    print("Categories: " + ", ".join(cfg.categories))
    return 0
