"""Tests for findings module: ID alloc, dataclass, JSON round-trip, corruption paths."""

import json
from pathlib import Path

import pytest

from sqa_tool import findings, paths


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
    raw = json.loads(paths.finding_path(initialized, fid).read_text())
    assert "id" not in raw


@pytest.mark.parametrize(
    "field,value",
    [
        ("severity", "critical"),
        ("triage", "bogus"),
    ],
)
def test_save_invalid_field(initialized: Path, field: str, value: str):
    fid = findings.alloc_id(initialized)
    f = findings.Finding(message="x", **{field: value})  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        findings.save_finding(initialized, fid, f)


def test_save_invalid_id(initialized: Path):
    with pytest.raises(ValueError):
        findings.save_finding(initialized, "lower", findings.Finding(message="x"))


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


# Corruption-path tests for load_finding: malformed JSON, wrong top-level type,
# missing required fields, and wrong-typed fields all surface as ValueError.


def _write_raw_finding(initialized: Path, payload: str) -> str:
    """Allocate an ID and write the raw payload directly to its finding path."""
    fid = findings.alloc_id(initialized)
    path = paths.finding_path(initialized, fid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload)
    return fid


def test_load_malformed_json(initialized: Path):
    fid = _write_raw_finding(initialized, "{not valid json")
    with pytest.raises(ValueError, match="invalid JSON"):
        findings.load_finding(initialized, fid)


@pytest.mark.parametrize(
    "payload",
    [
        '"just a string"',
        "[]",
        "42",
        "null",
    ],
)
def test_load_non_dict_top_level(initialized: Path, payload: str):
    fid = _write_raw_finding(initialized, payload)
    with pytest.raises(ValueError, match="expected a JSON object"):
        findings.load_finding(initialized, fid)


def test_load_missing_message_field(initialized: Path):
    fid = _write_raw_finding(initialized, json.dumps({"severity": "info"}))
    with pytest.raises(ValueError, match="missing required field"):
        findings.load_finding(initialized, fid)


@pytest.mark.parametrize(
    "data,match",
    [
        ({"message": 123}, "message must be a string"),
        ({"message": "ok", "rationale": 5}, "rationale must be a string"),
        ({"message": "ok", "related_files": "not-a-list"}, "related_files must be a list"),
        (
            {"message": "ok", "related_files": ["fine.py", 7]},
            r"related_files\[1\] must be a string",
        ),
        ({"message": "ok", "severity": 5}, "severity must be a string"),
        ({"message": "ok", "triage": 3}, "triage must be a string or null"),
    ],
)
def test_load_wrong_type_fields(initialized: Path, data: dict, match: str):
    fid = _write_raw_finding(initialized, json.dumps(data))
    with pytest.raises(ValueError, match=match):
        findings.load_finding(initialized, fid)
