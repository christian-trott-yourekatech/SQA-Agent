"""Tests for the orphans command."""

import json
from pathlib import Path

from conftest import _capture, _git, _run

from sqa_tool import findings


def test_orphans_empty_project(initialized: Path, capsys):
    out = json.loads(_capture(capsys, initialized, "orphans"))
    assert out["auto_fixed"]["deleted_empty_scope_files"] == []
    assert out["auto_fixed"]["added_related_files"] == []
    assert out["reported"]["findings_without_anchors"] == []
    assert out["reported"]["anchors_without_findings"] == []
    assert out["reported"]["stale_related_files"] == []


def test_orphans_deletes_empty_scope_md(initialized: Path, capsys):
    empty_md = initialized / "src" / ".sqa.md"
    empty_md.write_text("just a note, no anchors here\n")
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "empty md")

    out = json.loads(_capture(capsys, initialized, "orphans"))
    assert "src/.sqa.md" in out["auto_fixed"]["deleted_empty_scope_files"]
    assert not empty_md.exists()


def test_orphans_keeps_scope_md_with_anchors(initialized: Path, capsys):
    md = initialized / "src" / ".sqa.md"
    md.write_text("<!-- sqa: ABCDE -->\n")
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "anchored md")

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
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "anchor")

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
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "stray anchor")

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
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "with related")

    out = json.loads(_capture(capsys, initialized, "orphans"))
    stale = out["reported"]["stale_related_files"]
    assert any(item["id"] == fid for item in stale)


def test_resolve_deletes_finding(initialized: Path, capsys):
    """resolve must delete the finding JSON, not just mark it resolved.

    Audit trail lives in git history of the deletion, not in a persistent
    'status: resolved' state on disk.
    """
    fid = _capture(capsys, initialized, "record-finding", "--message=will be resolved").strip()
    assert fid in findings.list_finding_ids(initialized)

    _run(initialized, "resolve", fid, "--rationale=fixed")
    assert findings.list_finding_ids(initialized) == []


def test_resolve_strips_anchors_then_deletes(initialized: Path, capsys):
    """resolve must strip anchors from source and delete the finding JSON."""
    fid = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=fix the thing",
        "--anchor=src/sample.py",
        "--related=src/sample.py",
    ).strip()
    assert f"sqa: {fid}" in (initialized / "src" / "sample.py").read_text()

    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "anchor")

    _run(initialized, "resolve", fid, "--rationale=fixed")
    assert f"sqa: {fid}" not in (initialized / "src" / "sample.py").read_text()
    assert findings.list_finding_ids(initialized) == []
