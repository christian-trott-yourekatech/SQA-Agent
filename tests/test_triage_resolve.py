"""Tests for the v2.1 triage and resolve CLI commands."""

from pathlib import Path

from conftest import capture_cli, run_cli

from sqa_tool import paths
from sqa_tool.result_file import Finding, active_result_path, find_by_id, load_result

# --- Helpers --------------------------------------------------------------


def _start_and_record(monkeypatch, project: Path, capsys, **finding_kwargs) -> int:
    """Start a session and record one finding; return its allocated id."""
    capture_cli(capsys, monkeypatch, project, "start-result")
    args = [
        "record-finding",
        f"--message={finding_kwargs.get('message', 'some finding')}",
        f"--file={finding_kwargs.get('file', 'src/sample.py')}",
    ]
    return int(capture_cli(capsys, monkeypatch, project, *args).strip())


def _load_finding(project: Path, finding_id: int) -> Finding:
    sqa = paths.sqa_dir(project)
    path = active_result_path(sqa)
    assert path is not None
    return find_by_id(load_result(path), finding_id)


# --- triage: happy paths --------------------------------------------------


def test_triage_auto_keeps_open(initialized: Path, monkeypatch, capsys):
    fid = _start_and_record(monkeypatch, initialized, capsys)
    out = capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "auto",
        "--rationale=fix the bare Exception",
    )
    assert "auto (open)" in out

    f = _load_finding(initialized, fid)
    assert f.triage == "auto"
    assert f.status == "open"
    assert f.rationale == "fix the bare Exception"


def test_triage_interactive_keeps_open(initialized: Path, monkeypatch, capsys):
    fid = _start_and_record(monkeypatch, initialized, capsys)
    out = capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "interactive",
        "--rationale=needs discussion",
    )
    assert "interactive (open)" in out
    f = _load_finding(initialized, fid)
    assert (f.triage, f.status) == ("interactive", "open")


def test_triage_ignore_implies_resolved(initialized: Path, monkeypatch, capsys):
    fid = _start_and_record(monkeypatch, initialized, capsys)
    out = capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "ignore",
        "--rationale=not applicable in this codebase",
    )
    assert "ignore (resolved)" in out
    f = _load_finding(initialized, fid)
    assert (f.triage, f.status) == ("ignore", "resolved")


def test_triage_un_ignore_flips_back_to_open(initialized: Path, monkeypatch, capsys):
    fid = _start_and_record(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "ignore",
        "--rationale=skip",
    )
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "auto",
        "--rationale=actually do it",
    )
    f = _load_finding(initialized, fid)
    assert (f.triage, f.status) == ("auto", "open")
    assert f.rationale == "actually do it"


# --- triage: error paths --------------------------------------------------


def test_triage_unknown_id_errors(initialized: Path, monkeypatch, capsys):
    capture_cli(capsys, monkeypatch, initialized, "start-result")
    run_cli(
        monkeypatch,
        initialized,
        "triage",
        "99",
        "auto",
        "--rationale=x",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "no finding with id 99" in err


def test_triage_invalid_id_format_errors(initialized: Path, monkeypatch, capsys):
    import pytest

    capture_cli(capsys, monkeypatch, initialized, "start-result")
    # argparse `type=int` enforces this and raises SystemExit(2) with its
    # own message — it bypasses the cli's normal return-code path.
    monkeypatch.chdir(initialized)
    with pytest.raises(SystemExit) as exc:
        from sqa_tool.cli import main as cli_main

        cli_main(["triage", "abc", "auto", "--rationale=x"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid int value" in err


def test_triage_no_active_result_errors(initialized: Path, monkeypatch, capsys):
    run_cli(
        monkeypatch,
        initialized,
        "triage",
        "1",
        "auto",
        "--rationale=x",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "no active result" in err


def test_triage_rejects_reopen_of_action_resolved(initialized: Path, monkeypatch, capsys):
    """Once a finding is auto-resolved, re-triaging is rejected."""
    fid = _start_and_record(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "auto",
        "--rationale=fix it",
    )
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "resolve",
        str(fid),
        "--rationale=fixed",
    )
    run_cli(
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "interactive",
        "--rationale=reconsider",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "already resolved" in err


# --- resolve --------------------------------------------------------------


def test_resolve_flips_status(initialized: Path, monkeypatch, capsys):
    fid = _start_and_record(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "auto",
        "--rationale=fix it",
    )
    out = capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "resolve",
        str(fid),
        "--rationale=fixed by replacing Exception with AuthError",
    )
    assert "resolved" in out
    f = _load_finding(initialized, fid)
    assert f.status == "resolved"
    assert f.rationale == "fixed by replacing Exception with AuthError"


def test_resolve_does_not_delete(initialized: Path, monkeypatch, capsys):
    """v2.1 resolve keeps the entry; only status changes."""
    fid = _start_and_record(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "auto",
        "--rationale=fix",
    )
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "resolve",
        str(fid),
        "--rationale=done",
    )
    sqa = paths.sqa_dir(initialized)
    findings = load_result(active_result_path(sqa))  # type: ignore[arg-type]
    assert len(findings) == 1
    assert findings[0].id == fid


def test_resolve_untriaged_rejected(initialized: Path, monkeypatch, capsys):
    fid = _start_and_record(monkeypatch, initialized, capsys)
    run_cli(
        monkeypatch,
        initialized,
        "resolve",
        str(fid),
        "--rationale=skipping triage",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "triage first" in err


def test_resolve_already_resolved_rejected(initialized: Path, monkeypatch, capsys):
    fid = _start_and_record(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "auto",
        "--rationale=fix",
    )
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "resolve",
        str(fid),
        "--rationale=first",
    )
    run_cli(
        monkeypatch,
        initialized,
        "resolve",
        str(fid),
        "--rationale=second",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "already resolved" in err


def test_resolve_no_active_result_errors(initialized: Path, monkeypatch, capsys):
    run_cli(
        monkeypatch,
        initialized,
        "resolve",
        "1",
        "--rationale=x",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "no active result" in err


def test_resolve_after_triage_ignore_is_rejected(initialized: Path, monkeypatch, capsys):
    """ignore already flipped status=resolved; calling resolve is redundant."""
    fid = _start_and_record(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "triage",
        str(fid),
        "ignore",
        "--rationale=skip",
    )
    run_cli(
        monkeypatch,
        initialized,
        "resolve",
        str(fid),
        "--rationale=redundant",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "already resolved" in err
