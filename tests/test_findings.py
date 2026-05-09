"""Tests for findings module: ID alloc, dataclass, JSON round-trip."""

import json
from pathlib import Path

import pytest

from sqa_tool import findings


def test_id_format():
    for _ in range(100):
        i = findings.gen_id()
        assert findings.is_valid_id(i)
        assert len(i) == findings.ID_LENGTH
        assert all(c in findings.ID_ALPHABET for c in i)


def test_invalid_ids():
    assert not findings.is_valid_id("")
    assert not findings.is_valid_id("ABCD")  # too short
    assert not findings.is_valid_id("ABCDEF")  # too long
    assert not findings.is_valid_id("abcde")  # lowercase
    assert not findings.is_valid_id("ABC0E")  # 0 not in alphabet
    assert not findings.is_valid_id("ABC1E")  # 1 not in alphabet


def test_alloc_id_no_collision(initialized: Path):
    seen = set()
    for _ in range(50):
        i = findings.alloc_id(initialized)
        assert i not in seen
        seen.add(i)
        # Make it actually conflict on next iteration.
        findings.save_finding(initialized, i, findings.Finding(message="x"))


def test_save_load_round_trip(initialized: Path):
    f = findings.Finding(
        message="Test finding",
        severity="warning",
        triage="auto",
        status="open",
        rationale="because reasons",
        related_files=["src/foo.py", "src/bar.py"],
    )
    fid = findings.alloc_id(initialized)
    findings.save_finding(initialized, fid, f)
    loaded = findings.load_finding(initialized, fid)
    assert loaded == f


def test_no_id_field_in_json(initialized: Path):
    fid = findings.alloc_id(initialized)
    findings.save_finding(initialized, fid, findings.Finding(message="hi"))
    raw = json.loads((initialized / ".sqa" / "findings" / f"{fid}.json").read_text())
    assert "id" not in raw


def test_save_invalid_severity(initialized: Path):
    fid = findings.alloc_id(initialized)
    f = findings.Finding(message="x", severity="critical")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        findings.save_finding(initialized, fid, f)


def test_list_finding_ids(initialized: Path):
    assert findings.list_finding_ids(initialized) == []
    ids = []
    for _ in range(5):
        i = findings.alloc_id(initialized)
        findings.save_finding(initialized, i, findings.Finding(message="x"))
        ids.append(i)
    assert findings.list_finding_ids(initialized) == sorted(ids)


def test_load_missing_finding(initialized: Path):
    with pytest.raises(FileNotFoundError):
        findings.load_finding(initialized, "ZZZZZ")


def test_load_invalid_id_format(initialized: Path):
    with pytest.raises(ValueError):
        findings.load_finding(initialized, "lower")
