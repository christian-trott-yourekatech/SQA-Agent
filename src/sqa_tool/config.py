"""Loading and validation of .sqa/config.toml."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from sqa_tool import paths


@dataclass
class Config:
    """Resolved project configuration."""

    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


DEFAULT_CONFIG_TEXT = """\
# sqa-tool project configuration.

[files]
# Glob patterns (relative to project root) of files to include in review.
# Intersected with `git ls-files`, so untracked files are never reviewed.
include = []

# Patterns to exclude from the include set.
exclude = []
"""


def load_config(project_root: Path) -> Config:
    """Load .sqa/config.toml.

    Raises FileNotFoundError if the config file does not exist. A missing
    [files] section, or missing include/exclude keys within it, default to
    empty lists.
    """
    path = paths.config_path(project_root)
    if not path.exists():
        raise FileNotFoundError(f"No config file at {path}. Run `sqa-tool init` first.")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    files = data.get("files", {})
    include = files.get("include", [])
    exclude = files.get("exclude", [])
    if not isinstance(include, list) or not all(isinstance(x, str) for x in include):
        raise ValueError("config: [files].include must be a list of strings")
    if not isinstance(exclude, list) or not all(isinstance(x, str) for x in exclude):
        raise ValueError("config: [files].exclude must be a list of strings")
    return Config(include=include, exclude=exclude)
