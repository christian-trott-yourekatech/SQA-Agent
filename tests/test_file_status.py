"""Tests for the fcntl-locked file_status module."""

# sqa: LJ3E4
import json
from pathlib import Path

import pytest

from sqa_tool import file_status, paths


def test_load_empty(initialized: Path):
    assert file_status.load(initialized) == {}


def test_update_creates_entry(initialized: Path):
    file_status.update(initialized, "src/foo.py", "abc123")
    assert file_status.load(initialized) == {"src/foo.py": "abc123"}


def test_update_replaces_entry(initialized: Path):
    file_status.update(initialized, "src/foo.py", "abc123")
    file_status.update(initialized, "src/foo.py", "def456")
    assert file_status.load(initialized) == {"src/foo.py": "def456"}


def test_multiple_entries(initialized: Path):
    file_status.update(initialized, "src/a.py", "h1")
    file_status.update(initialized, "src/b.py", "h2")
    file_status.update(initialized, "src/c.py", "h3")
    assert file_status.load(initialized) == {
        "src/a.py": "h1",
        "src/b.py": "h2",
        "src/c.py": "h3",
    }


def test_remove(initialized: Path):
    file_status.update(initialized, "src/a.py", "h1")
    file_status.update(initialized, "src/b.py", "h2")
    file_status.remove(initialized, "src/a.py")
    assert file_status.load(initialized) == {"src/b.py": "h2"}


def test_persisted_format_is_json(initialized: Path):
    file_status.update(initialized, "x.py", "hash1")
    raw = paths.file_status_path(initialized).read_text()
    assert json.loads(raw) == {"x.py": "hash1"}


def test_remove_missing_key_is_noop(initialized: Path):
    file_status.update(initialized, "src/a.py", "h1")
    file_status.remove(initialized, "src/does_not_exist.py")
    assert file_status.load(initialized) == {"src/a.py": "h1"}


def test_remove_on_empty_store_is_noop(initialized: Path):
    file_status.remove(initialized, "src/missing.py")
    assert file_status.load(initialized) == {}


def test_remove_on_missing_file_is_noop(initialized: Path):
    status_path = paths.file_status_path(initialized)
    status_path.unlink()
    file_status.remove(initialized, "src/missing.py")
    assert file_status.load(initialized) == {}


def test_load_on_missing_file_returns_empty(initialized: Path):
    status_path = paths.file_status_path(initialized)
    status_path.unlink()
    assert file_status.load(initialized) == {}


def test_load_raises_on_corrupt_json(initialized: Path):
    status_path = paths.file_status_path(initialized)
    status_path.write_text("{not valid json")
    with pytest.raises(RuntimeError, match="Corrupt file_status"):
        file_status.load(initialized)


def test_update_raises_on_corrupt_json(initialized: Path):
    status_path = paths.file_status_path(initialized)
    status_path.write_text("{not valid json")
    with pytest.raises(RuntimeError, match="Corrupt file_status"):
        file_status.update(initialized, "src/a.py", "h1")


def test_remove_raises_on_corrupt_json(initialized: Path):
    status_path = paths.file_status_path(initialized)
    status_path.write_text("{not valid json")
    with pytest.raises(RuntimeError, match="Corrupt file_status"):
        file_status.remove(initialized, "src/anything.py")
