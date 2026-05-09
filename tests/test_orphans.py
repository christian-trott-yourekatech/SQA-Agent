"""Tests for the orphans command."""

import json
from pathlib import Path

from conftest import _capture, _commit

from sqa_tool import findings


def test_orphans_empty_project(initialized: Path, capsys):
    out = json.loads(_capture(capsys, initialized, "orphans"))
    assert out["auto_fixed"]["deleted_empty_scope_files"] == []
    assert out["auto_fixed"]["added_related_files"] == []
    assert out["reported"]["findings_without_anchors"] == []
    assert out["reported"]["anchors_without_findings"] == []
    assert out["reported"]["stale_related_files"] == []
    assert out["reported"]["unreadable_findings"] == []


def test_orphans_reports_unreadable_finding(initialized: Path, capsys):
    # Write a malformed finding JSON directly to disk; orphans should surface
    # the ID under reported.unreadable_findings rather than crashing.
    bad = initialized / ".sqa" / "findings" / "BADID.json"
    bad.write_text("{not valid json")
    _commit(initialized)

    out = json.loads(_capture(capsys, initialized, "orphans"))
    assert "BADID" in out["reported"]["unreadable_findings"]


def test_orphans_deletes_empty_scope_md(initialized: Path, capsys):
    empty_md = initialized / "src" / ".sqa.md"
    empty_md.write_text("just a note, no anchors here\n")
    _commit(initialized)

    out = json.loads(_capture(capsys, initialized, "orphans"))
    assert "src/.sqa.md" in out["auto_fixed"]["deleted_empty_scope_files"]
    assert not empty_md.exists()


def test_orphans_keeps_scope_md_with_anchors(initialized: Path, capsys):
    md = initialized / "src" / ".sqa.md"
    md.write_text("<!-- sqa: ABCDE -->\n")
    _commit(initialized)

    out = json.loads(_capture(capsys, initialized, "orphans"))
    assert out["auto_fixed"]["deleted_empty_scope_files"] == []
    assert md.exists()


def test_orphans_adds_anchor_file_to_related(initialized: Path, capsys):
    # Record a finding with --anchor=src/sample.py but NO --related.
    fid = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=fix this",
        "--anchor=src/sample.py",
    ).strip()
    _commit(initialized)

    f = findings.load_finding(initialized, fid)
    assert f.related_files == []  # not yet auto-fixed

    out = json.loads(_capture(capsys, initialized, "orphans"))
    added = out["auto_fixed"]["added_related_files"]
    assert any(item["id"] == fid and item["added"] == "src/sample.py" for item in added)

    f2 = findings.load_finding(initialized, fid)
    assert "src/sample.py" in f2.related_files


def test_orphans_reports_anchor_without_finding(initialized: Path, capsys):
    # Manually insert an anchor for a non-existent finding ID.
    sample = initialized / "src" / "sample.py"
    sample.write_text("# sqa: ZZZZZ\n" + sample.read_text())
    _commit(initialized)

    out = json.loads(_capture(capsys, initialized, "orphans"))
    reported = out["reported"]["anchors_without_findings"]
    assert any(item["id"] == "ZZZZZ" for item in reported)


def test_orphans_reports_finding_without_anchor(initialized: Path, capsys):
    # Record a finding without --anchor (LLM is supposed to insert it but didn't).
    fid = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=somewhere",
        "--related=src/sample.py",
    ).strip()

    out = json.loads(_capture(capsys, initialized, "orphans"))
    assert fid in out["reported"]["findings_without_anchors"]


def test_orphans_reports_stale_related_files(initialized: Path, capsys):
    # Record a finding referring to a file that doesn't exist.
    fid = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=missing",
        "--related=src/does_not_exist.py",
        "--anchor=src/sample.py",
    ).strip()
    _commit(initialized)

    out = json.loads(_capture(capsys, initialized, "orphans"))
    stale = out["reported"]["stale_related_files"]
    assert any(item["id"] == fid for item in stale)
