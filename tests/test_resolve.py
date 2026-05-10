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
    assert "error:" in out


def test_resolve_echoes_rationale(initialized: Path, capsys, monkeypatch):
    """resolve must echo the --rationale to stdout as confirmation (not persisted)."""
    fid = _capture(
        capsys, monkeypatch, initialized, "record-finding", "--message=will be resolved"
    ).strip()
    out = _capture(capsys, monkeypatch, initialized, "resolve", fid, "--rationale=because reasons")
    assert "because reasons" in out


def test_resolve_proceeds_when_json_is_corrupt(initialized: Path, capsys, monkeypatch):
    """resolve must succeed even when the JSON is corrupt: strip anchors and
    delete the JSON. Aborting would leave anchors with no tool path to clean
    them up — the user would have to edit source files manually.
    """
    fid = "ABCDE"
    findings_dir = initialized / ".sqa" / "findings"
    (findings_dir / f"{fid}.json").write_text("{not valid json")
    sample = initialized / "src" / "sample.py"
    sample.write_text(f"# sqa: {fid}\n" + sample.read_text())
    _commit(initialized)

    rc = _run(monkeypatch, initialized, "resolve", fid, "--rationale=cleanup corrupt")
    assert rc == 0
    assert f"sqa: {fid}" not in sample.read_text()
    assert not (findings_dir / f"{fid}.json").exists()


def test_resolve_rejects_invalid_id_format(initialized: Path, capsys, monkeypatch):
    """resolve must reject IDs that don't match the base32 alphabet up front,
    so a malformed ID can't fall into the corrupt-JSON proceed-anyway path.
    """
    rc = _run(
        monkeypatch, initialized, "resolve", "NOPE0", "--rationale=ignored", expected_exit=1
    )
    assert rc == 1


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
