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
    categories: list[str] = field(default_factory=list)


# Default categories used when none are configured. Matches the suggestions
# in Docs/design.md § 5.1. Project owners are expected to edit
# config.toml to taste; this is a starting list, not a contract.
DEFAULT_CATEGORIES = [
    "dry-ssot",
    "interfaces",
    "logic",
    "comments",
    "error-handling",
    "kiss-yagni",
    "security",
    "project-specific",
]


# Built from DEFAULT_CATEGORIES so the canonical list lives in exactly one
# place. Keep the two-space indent and quoted entries to match the existing
# TOML style; init.py writes this verbatim into .sqa/config.toml.
#
# Note: this f-string interpolation assumes category names are TOML-safe
# (no embedded double-quotes or backslashes), which trivially holds for the
# hard-coded DEFAULT_CATEGORIES literal above. If DEFAULT_CATEGORIES is ever
# expanded with names containing quotes or backslashes, this would emit
# malformed TOML — at that point, escape the name or switch to a real TOML
# emitter.
_DEFAULT_CATEGORIES_TOML = "\n".join(f'  "{name}",' for name in DEFAULT_CATEGORIES)

DEFAULT_CONFIG_TEXT = f"""\
# sqa-tool project configuration.

[files]
# Glob patterns (relative to project root) of files to include in review.
# Intersected with `git ls-files`, so untracked files are never reviewed.
include = []

# Patterns to exclude from the include set.
exclude = []

[categories]
# Canonical list of review categories. The review-file framework subagent
# fetches this list (via `sqa-tool categories`) and tags each finding with
# one. The CLI's --category flag uses it for soft validation (unknown
# values warn). The project review prompt itself stays tool-agnostic and
# doesn't mention this list.
list = [
{_DEFAULT_CATEGORIES_TOML}
]
"""


def _require_list_of_str(value: object, label: str) -> None:
    """Raise ValueError if value is not a list whose elements are all strings.

    `label` names the offending config key in the error message (e.g.
    '[files].include') so users can find it without grepping.
    """
    if not isinstance(value, list):
        raise ValueError(f"config: {label} must be a list")
    for i, x in enumerate(value):
        if not isinstance(x, str):
            raise ValueError(f"config: {label}[{i}] must be a string, got {type(x).__name__}")


def load_config(project_root: Path) -> Config:
    """Load .sqa/config.toml.

    Raises FileNotFoundError if the config file does not exist. A missing
    [files] section, or missing include/exclude keys within it, default to
    empty lists.

    Categories handling: see _load_categories.
    """
    path = paths.config_path(project_root)
    if not path.exists():
        raise FileNotFoundError(f"No config file at {path}. Run `sqa-tool init` first.")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    files = data.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("config: [files] must be a table")
    include = files.get("include", [])
    exclude = files.get("exclude", [])
    _require_list_of_str(include, "[files].include")
    _require_list_of_str(exclude, "[files].exclude")
    categories = _load_categories(data)
    # Config fields are independent lists, owned by Config — never aliasing
    # tomllib's parsed data or module-level defaults. This is the single
    # defensive-copy boundary; _load_categories returns raw references.
    return Config(include=list(include), exclude=list(exclude), categories=list(categories))


def _load_categories(data: dict[str, object]) -> list[str]:
    """Read `[categories].list` from a parsed config, falling back to defaults.

    A missing `[categories]` section, or a `[categories]` section without a
    `list` key, yields the default list. An explicit `list = []` is honored
    as-is (the project actively declares no categories). Review is still
    useful without project-specific categories, so refusing to start here
    would be more annoying than helpful.
    """
    section = data.get("categories", {})
    if not isinstance(section, dict):
        raise ValueError("config: [categories] must be a table")
    raw = section.get("list", None)
    if raw is None:
        return DEFAULT_CATEGORIES
    _require_list_of_str(raw, "[categories].list")
    return raw
