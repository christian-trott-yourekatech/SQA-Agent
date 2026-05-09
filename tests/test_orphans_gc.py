"""Tests for orphans + gc commands."""

import json
import os
import time
from pathlib import Path

from conftest import _git, _run

from sqa_tool import findings
from sqa_tool.commands.gc import parse_duration


def test_parse_duration():
    assert parse_duration("30d") == 30 * 86400
    assert parse_duration("24h") == 24 * 3600
    assert parse_duration("1w") == 7 * 86400
    assert parse_duration("5m") == 5 * 60
    assert parse_duration("10s") == 10


def test_parse_duration_invalid():
    import pytest

    with pytest.raises(ValueError):
        parse_duration("abc")
    with pytest.raises(ValueError):
        parse_duration("")
    with pytest.raises(ValueError):
        parse_duration("5y")


def test_orphans_empty_project(initialized: Path, capsys):
    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
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

    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
    assert "src/.sqa.md" in out["auto_fixed"]["deleted_empty_scope_files"]
    assert not empty_md.exists()


def test_orphans_keeps_scope_md_with_anchors(initialized: Path, capsys):
    md = initialized / "src" / ".sqa.md"
    md.write_text("<!-- sqa: ABCDE -->\n")
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "anchored md")

    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
    assert out["auto_fixed"]["deleted_empty_scope_files"] == []
    assert md.exists()


def test_orphans_adds_anchor_file_to_related(initialized: Path, capsys):
    # Record a finding with --anchor=src/sample.py but NO --related.
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=fix this",
        "--anchor=src/sample.py",
    )
    fid = capsys.readouterr().out.strip()
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "anchor")

    f = findings.load_finding(initialized, fid)
    assert f.related_files == []  # not yet auto-fixed

    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
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

    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
    reported = out["reported"]["anchors_without_findings"]
    assert any(item["id"] == "ZZZZZ" for item in reported)


def test_orphans_reports_finding_without_anchor(initialized: Path, capsys):
    # Record a finding without --anchor (LLM is supposed to insert it but didn't).
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=somewhere",
        "--related=src/sample.py",
    )
    fid = capsys.readouterr().out.strip()

    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
    assert fid in out["reported"]["findings_without_anchors"]


def test_orphans_does_not_report_resolved_findings(initialized: Path, capsys):
    # Resolved findings have their anchors stripped by design — they should
    # NOT show up in findings_without_anchors. Only OPEN findings missing an
    # anchor are real orphans.
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=will be resolved",
        "--anchor=src/sample.py",
        "--related=src/sample.py",
    )
    fid = capsys.readouterr().out.strip()

    # Resolve it — this strips the anchor but keeps the JSON file.
    _run(initialized, "resolve", fid, "--rationale=fixed")

    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
    assert fid not in out["reported"]["findings_without_anchors"], (
        f"Resolved finding {fid} should not appear as an orphan"
    )


def test_orphans_reports_stale_related_files(initialized: Path, capsys):
    # Record a finding referring to a file that doesn't exist.
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=missing",
        "--related=src/does_not_exist.py",
        "--anchor=src/sample.py",
    )
    fid = capsys.readouterr().out.strip()
    _git(initialized, "add", ".")
    _git(initialized, "commit", "-q", "-m", "with related")

    capsys.readouterr()
    _run(initialized, "orphans")
    out = json.loads(capsys.readouterr().out)
    stale = out["reported"]["stale_related_files"]
    assert any(item["id"] == fid for item in stale)


def test_gc_zero_window_deletes_everything(initialized: Path, capsys):
    capsys.readouterr()
    _run(initialized, "record-finding", "--message=x")
    fid = capsys.readouterr().out.strip()
    _run(initialized, "resolve", fid, "--rationale=done")

    capsys.readouterr()
    _run(initialized, "gc", "--older-than=0s")
    assert "deleted 1" in capsys.readouterr().out
    assert findings.list_finding_ids(initialized) == []


def test_gc_older_than_keeps_recent(initialized: Path, capsys):
    capsys.readouterr()
    _run(initialized, "record-finding", "--message=x")
    fid = capsys.readouterr().out.strip()
    _run(initialized, "resolve", fid, "--rationale=done")

    capsys.readouterr()
    _run(initialized, "gc", "--older-than=1d")
    # File was just modified — gc with 1d window should not delete it.
    assert "deleted 0" in capsys.readouterr().out
    assert fid in findings.list_finding_ids(initialized)


def test_gc_older_than_deletes_old(initialized: Path, capsys):
    from sqa_tool import paths

    capsys.readouterr()
    _run(initialized, "record-finding", "--message=x")
    fid = capsys.readouterr().out.strip()
    _run(initialized, "resolve", fid, "--rationale=done")

    # Backdate the file to look 30 days old.
    finding_path = paths.finding_path(initialized, fid)
    old = time.time() - 30 * 86400
    os.utime(finding_path, (old, old))

    capsys.readouterr()
    _run(initialized, "gc", "--older-than=7d")
    assert "deleted 1" in capsys.readouterr().out
    assert findings.list_finding_ids(initialized) == []


def test_gc_skips_open_findings(initialized: Path, capsys):
    capsys.readouterr()
    _run(initialized, "record-finding", "--message=x")
    fid = capsys.readouterr().out.strip()
    # Don't resolve; leave open.

    capsys.readouterr()
    _run(initialized, "gc", "--older-than=0s")
    assert "deleted 0" in capsys.readouterr().out
    assert fid in findings.list_finding_ids(initialized)
