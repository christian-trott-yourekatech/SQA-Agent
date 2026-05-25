"""Tests for the v2.1 read-side CLI commands: show-finding, list-findings,
status, findings-for-file."""

import json
import time
from pathlib import Path

from conftest import capture_cli, run_cli

# --- Helpers --------------------------------------------------------------


def _start(monkeypatch, project: Path, capsys) -> Path:
    out = capture_cli(capsys, monkeypatch, project, "start-result")
    return Path(out.strip().splitlines()[0])


def _record(monkeypatch, project: Path, capsys, **kwargs) -> int:
    args = ["record-finding", f"--message={kwargs.get('message', 'm')}"]
    if "file" in kwargs:
        args.append(f"--file={kwargs['file']}")
    if "category" in kwargs:
        args.append(f"--category={kwargs['category']}")
    if "severity" in kwargs:
        args.append(f"--severity={kwargs['severity']}")
    for r in kwargs.get("related", []):
        args.append(f"--related={r}")
    return int(capture_cli(capsys, monkeypatch, project, *args).strip())


def _triage(monkeypatch, project: Path, capsys, fid: int, decision: str, rationale: str = "x"):
    capture_cli(
        capsys,
        monkeypatch,
        project,
        "triage",
        str(fid),
        decision,
        f"--rationale={rationale}",
    )


# --- show-finding ---------------------------------------------------------


def test_show_finding_prints_full_record(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    fid = _record(
        monkeypatch,
        initialized,
        capsys,
        message="raise Exception",
        file="src/sample.py",
        category="error-handling",
        severity="warning",
    )
    out = capture_cli(capsys, monkeypatch, initialized, "show-finding", str(fid))
    data = json.loads(out)
    assert data["id"] == fid
    assert data["message"] == "raise Exception"
    assert data["file"] == "src/sample.py"
    assert data["category"] == "error-handling"
    assert data["severity"] == "warning"
    assert data["status"] == "open"


def test_show_finding_missing_errors(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    run_cli(monkeypatch, initialized, "show-finding", "999", expected_exit=1)
    err = capsys.readouterr().err
    assert "no finding with id 999" in err


def test_show_finding_invalid_id_errors(initialized: Path, monkeypatch, capsys):
    import pytest

    _start(monkeypatch, initialized, capsys)
    # argparse `type=int` enforces this and raises SystemExit(2) with its
    # own message — it bypasses the cli's normal return-code path.
    monkeypatch.chdir(initialized)
    with pytest.raises(SystemExit) as exc:
        from sqa_tool.cli import main as cli_main

        cli_main(["show-finding", "notanint"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "invalid int value" in err


def test_show_finding_no_active_result_errors(initialized: Path, monkeypatch, capsys):
    # No start-result yet → no findings to show.
    run_cli(monkeypatch, initialized, "show-finding", "1", expected_exit=1)


# --- list-findings --------------------------------------------------------


def test_list_findings_empty_session(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    out = capture_cli(capsys, monkeypatch, initialized, "list-findings")
    assert json.loads(out) == []


def test_list_findings_no_active_yields_empty(initialized: Path, monkeypatch, capsys):
    """The loop guard `list-findings --count` should answer 0, not error,
    when no session has been started."""
    out = capture_cli(capsys, monkeypatch, initialized, "list-findings", "--count")
    assert out.strip() == "0"


def test_list_findings_count(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    _record(monkeypatch, initialized, capsys, message="a", file="x.py")
    _record(monkeypatch, initialized, capsys, message="b", file="y.py")
    out = capture_cli(capsys, monkeypatch, initialized, "list-findings", "--count")
    assert out.strip() == "2"


def test_list_findings_triage_filter(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    a = _record(monkeypatch, initialized, capsys, message="a", file="x.py")
    b = _record(monkeypatch, initialized, capsys, message="b", file="y.py")
    _record(monkeypatch, initialized, capsys, message="c", file="z.py")  # untriaged
    _triage(monkeypatch, initialized, capsys, a, "auto")
    _triage(monkeypatch, initialized, capsys, b, "interactive")

    auto_only = json.loads(
        capture_cli(capsys, monkeypatch, initialized, "list-findings", "--triage=auto")
    )
    assert [f["id"] for f in auto_only] == [a]

    untriaged = json.loads(
        capture_cli(capsys, monkeypatch, initialized, "list-findings", "--triage=untriaged")
    )
    assert len(untriaged) == 1
    assert untriaged[0]["triage"] is None


def test_list_findings_status_filter(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    a = _record(monkeypatch, initialized, capsys, message="a", file="x.py")
    b = _record(monkeypatch, initialized, capsys, message="b", file="y.py")
    _triage(monkeypatch, initialized, capsys, a, "auto")
    _triage(monkeypatch, initialized, capsys, b, "ignore")  # → resolved

    open_only = json.loads(
        capture_cli(capsys, monkeypatch, initialized, "list-findings", "--status=open")
    )
    assert [f["id"] for f in open_only] == [a]
    resolved = json.loads(
        capture_cli(capsys, monkeypatch, initialized, "list-findings", "--status=resolved")
    )
    assert [f["id"] for f in resolved] == [b]


def test_list_findings_combined_filters(initialized: Path, monkeypatch, capsys):
    """Auto + open is the common gate query in `sqa-resolve auto`."""
    _start(monkeypatch, initialized, capsys)
    a = _record(monkeypatch, initialized, capsys, message="a", file="x.py")
    b = _record(monkeypatch, initialized, capsys, message="b", file="y.py")
    _triage(monkeypatch, initialized, capsys, a, "auto")
    _triage(monkeypatch, initialized, capsys, b, "auto")
    capture_cli(capsys, monkeypatch, initialized, "resolve", str(a), "--rationale=fixed")
    out = json.loads(
        capture_cli(
            capsys,
            monkeypatch,
            initialized,
            "list-findings",
            "--triage=auto",
            "--status=open",
        )
    )
    assert [f["id"] for f in out] == [b]


def test_list_findings_limit(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    for i in range(5):
        _record(monkeypatch, initialized, capsys, message=f"m{i}", file=f"f{i}.py")
    out = json.loads(capture_cli(capsys, monkeypatch, initialized, "list-findings", "--limit=2"))
    assert len(out) == 2


# --- status ---------------------------------------------------------------


def test_status_empty_session(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    data = json.loads(capture_cli(capsys, monkeypatch, initialized, "status"))
    assert data["total"] == 0
    assert data["by_triage"] == {}
    assert data["by_severity"] == {}
    assert data["by_status"] == {}
    assert data["result_file"] is not None


def test_status_with_findings(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    a = _record(monkeypatch, initialized, capsys, message="m", file="x.py", severity="warning")
    b = _record(monkeypatch, initialized, capsys, message="m", file="y.py", severity="info")
    _triage(monkeypatch, initialized, capsys, a, "auto")
    _triage(monkeypatch, initialized, capsys, b, "ignore")
    data = json.loads(capture_cli(capsys, monkeypatch, initialized, "status"))
    assert data["total"] == 2
    assert data["by_triage"] == {"auto": 1, "ignore": 1}
    assert data["by_severity"] == {"warning": 1, "info": 1}
    assert data["by_status"] == {"open": 1, "resolved": 1}


def test_status_no_active_returns_zero(initialized: Path, monkeypatch, capsys):
    data = json.loads(capture_cli(capsys, monkeypatch, initialized, "status"))
    assert data["total"] == 0
    assert data["result_file"] is None


# --- findings-for-file ----------------------------------------------------


def test_findings_for_file_by_file_field(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    a = _record(monkeypatch, initialized, capsys, message="m", file="src/x.py")
    _record(monkeypatch, initialized, capsys, message="m", file="src/y.py")
    out = json.loads(capture_cli(capsys, monkeypatch, initialized, "findings-for-file", "src/x.py"))
    assert [f["id"] for f in out] == [a]


def test_findings_for_file_by_related(initialized: Path, monkeypatch, capsys):
    """Cross-file findings surface in every related file's listing."""
    _start(monkeypatch, initialized, capsys)
    a = _record(
        monkeypatch,
        initialized,
        capsys,
        message="dry",
        file="src/x.py",
        related=["src/y.py"],
    )
    out = json.loads(capture_cli(capsys, monkeypatch, initialized, "findings-for-file", "src/y.py"))
    assert [f["id"] for f in out] == [a]


def test_findings_for_file_empty(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    _record(monkeypatch, initialized, capsys, message="m", file="src/x.py")
    out = json.loads(
        capture_cli(capsys, monkeypatch, initialized, "findings-for-file", "src/unrelated.py")
    )
    assert out == []


# --- --from (read-only access to historical results) ----------------------


def test_from_reads_older_result(initialized: Path, monkeypatch, capsys):
    """A previous session's findings remain readable via --from after a new
    start-result has rotated the active pointer.

    The first session is closed out (ignore-triage flips status to
    resolved) so the second start-result passes the unresolved-findings
    safety guard.
    """
    first = _start(monkeypatch, initialized, capsys)
    fid = _record(monkeypatch, initialized, capsys, message="first-finding", file="x.py")
    _triage(monkeypatch, initialized, capsys, fid, "ignore")

    # New session — `active` now points elsewhere.
    time.sleep(1.05)
    _start(monkeypatch, initialized, capsys)
    assert json.loads(capture_cli(capsys, monkeypatch, initialized, "list-findings")) == []

    historical = json.loads(
        capture_cli(
            capsys,
            monkeypatch,
            initialized,
            "list-findings",
            f"--from={first.name}",
        )
    )
    assert len(historical) == 1
    assert historical[0]["message"] == "first-finding"


def test_from_missing_file_errors(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    run_cli(
        monkeypatch,
        initialized,
        "list-findings",
        "--from=result_2099_01_01_000000.json",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "does not exist" in err
