"""sqa-tool categories — print the project's review-category list.

One name per line. Used by `review-file` subagents to learn what categories
exist before tagging findings with `--category`. Falls back to the defaults
in :mod:`sqa_tool.config` if `config.toml` has no `[categories]` section.
"""

import argparse
from pathlib import Path

from sqa_tool.config import load_config


def run(project_root: Path, args: argparse.Namespace) -> int:
    cfg = load_config(project_root)
    for name in cfg.categories:
        print(name)
    return 0
