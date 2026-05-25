"""Tests for .sqa/config.toml loading."""

from pathlib import Path

import pytest

from sqa_tool import paths
from sqa_tool.config import DEFAULT_CATEGORIES, load_config


def _write_config(project: Path, body: str) -> None:
    cfg = paths.config_path(project)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(body)


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="No config file"):
        load_config(tmp_path)


def test_load_with_files_block(tmp_path: Path):
    _write_config(
        tmp_path,
        '[files]\ninclude = ["src/**/*.py"]\nexclude = ["src/**/*_test.py"]\n',
    )
    cfg = load_config(tmp_path)
    assert cfg.include == ["src/**/*.py"]
    assert cfg.exclude == ["src/**/*_test.py"]


def test_categories_default_when_absent(tmp_path: Path):
    """Missing [categories] is permissible — defaults are filled in."""
    _write_config(tmp_path, "[files]\ninclude = []\nexclude = []\n")
    cfg = load_config(tmp_path)
    assert cfg.categories == DEFAULT_CATEGORIES


def test_categories_default_when_list_omitted(tmp_path: Path):
    """A [categories] table with no `list` key falls back to defaults."""
    _write_config(tmp_path, "[files]\ninclude = []\nexclude = []\n[categories]\n")
    cfg = load_config(tmp_path)
    assert cfg.categories == DEFAULT_CATEGORIES


def test_categories_explicit_list(tmp_path: Path):
    _write_config(
        tmp_path,
        '[files]\ninclude = []\nexclude = []\n[categories]\nlist = ["a", "b", "c"]\n',
    )
    cfg = load_config(tmp_path)
    assert cfg.categories == ["a", "b", "c"]


def test_categories_explicit_empty_list_honored(tmp_path: Path):
    """An explicit empty list is honored (not replaced by defaults).

    Rationale: an empty list could be a deliberate "no categories" choice;
    treat it differently from "not configured at all".
    """
    _write_config(
        tmp_path,
        "[files]\ninclude = []\nexclude = []\n[categories]\nlist = []\n",
    )
    cfg = load_config(tmp_path)
    assert cfg.categories == []


def test_categories_rejects_non_string_entries(tmp_path: Path):
    _write_config(
        tmp_path,
        "[files]\ninclude = []\nexclude = []\n[categories]\nlist = [1, 2]\n",
    )
    with pytest.raises(ValueError, match="categories"):
        load_config(tmp_path)


def test_categories_rejects_non_list_value(tmp_path: Path):
    _write_config(
        tmp_path,
        '[files]\ninclude = []\nexclude = []\n[categories]\nlist = "logic"\n',
    )
    with pytest.raises(ValueError, match="categories"):
        load_config(tmp_path)


def test_default_categories_constant_matches_design():
    """Pinned: the default list documented in Docs/design.md § 5.1 should
    match what code emits."""
    expected = {
        "dry-ssot",
        "interfaces",
        "logic",
        "comments",
        "error-handling",
        "kiss-yagni",
        "security",
        "project-specific",
    }
    assert set(DEFAULT_CATEGORIES) == expected
