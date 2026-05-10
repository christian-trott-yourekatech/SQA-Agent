"""Tests for the resolve command."""

from pathlib import Path

from conftest import _capture, _commit, _run

from sqa_tool import findings


def test_resolve_deletes_finding(initialized: Path, capsys, monkeypatch):
    """resolve must delete the finding JSON, not just mark it resolved.

    Audit trail lives in git history of the deletion, not in a persistent
    'status: resolved' state on disk.
    """
    fid = _capture(
        capsys, monkeypatch, initialized, "record-finding", "--message=will be resolved"
    ).strip()
    assert fid in findings.list_finding_ids(initialized)

    _run(monkeypatch, initialized, "resolve", fid, "--rationale=fixed")
    assert findings.list_finding_ids(initialized) == []


def test_resolve_unknown_id_errors(initialized: Path, capsys, monkeypatch):
    """resolve with an unknown finding ID must print 'error: ...' and exit 1."""
    capsys.readouterr()
    _run(monkeypatch, initialized, "resolve", "NOPE0", "--rationale=irrelevant", expected_exit=1)
    out = capsys.readouterr().out
    assert out.startswith("error:") or "error:" in out


def test_resolve_echoes_rationale(initialized: Path, capsys, monkeypatch):
    """resolve must echo the --rationale to stdout as confirmation (not persisted)."""
    fid = _capture(
        capsys, monkeypatch, initialized, "record-finding", "--message=will be resolved"
    ).strip()
    out = _capture(capsys, monkeypatch, initialized, "resolve", fid, "--rationale=because reasons")
    assert "because reasons" in out


def test_resolve_strips_anchors_then_deletes(initialized: Path, capsys, monkeypatch):
    """resolve must strip anchors from source and delete the finding JSON."""
    fid = _capture(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=fix the thing",
        "--anchor=src/sample.py",
        "--related=src/sample.py",
    ).strip()
    assert f"sqa: {fid}" in (initialized / "src" / "sample.py").read_text()

    _commit(initialized)

    _run(monkeypatch, initialized, "resolve", fid, "--rationale=fixed")
    assert f"sqa: {fid}" not in (initialized / "src" / "sample.py").read_text()
    assert findings.list_finding_ids(initialized) == []
