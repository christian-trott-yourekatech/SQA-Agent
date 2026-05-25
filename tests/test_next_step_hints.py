"""Tests for next-step hints emitted on stderr by gate commands.

The principle: stdout stays pure (so shell capture like `$(... --count)` keeps
working as an integer), and the hint goes to stderr where the skill agent
can read it.
"""

from pathlib import Path

from conftest import capture_cli, run_cli


def _start(monkeypatch, project: Path, capsys) -> None:
    capture_cli(capsys, monkeypatch, project, "start-result")


def _record(monkeypatch, project: Path, capsys, **kwargs) -> int:
    args = ["record-finding", f"--message={kwargs.get('message', 'm')}"]
    if "file" in kwargs:
        args.append(f"--file={kwargs['file']}")
    return int(capture_cli(capsys, monkeypatch, project, *args).strip())


def _triage(monkeypatch, project: Path, capsys, fid: int, decision: str):
    capture_cli(
        capsys,
        monkeypatch,
        project,
        "triage",
        str(fid),
        decision,
        "--rationale=x",
    )


# --- needs-review hints ---------------------------------------------------


def test_needs_review_count_zero_hint(initialized: Path, monkeypatch, capsys):
    # No tracked files match the empty default include list, so count is 0.
    run_cli(monkeypatch, initialized, "needs-review", "--count")
    captured = capsys.readouterr()
    assert captured.out.strip() == "0"
    assert "hint:" in captured.err
    assert "review" in captured.err.lower() or "status" in captured.err.lower()


def test_needs_review_count_positive_hint(configured: Path, monkeypatch, capsys):
    run_cli(monkeypatch, configured, "needs-review", "--count")
    captured = capsys.readouterr()
    assert captured.out.strip() == "1"
    assert "hint:" in captured.err
    assert "files remain" in captured.err.lower()


def test_needs_review_non_count_no_hint(configured: Path, monkeypatch, capsys):
    """The non-count form returns the actual file list; no hint to stderr."""
    run_cli(monkeypatch, configured, "needs-review")
    err = capsys.readouterr().err
    assert "hint:" not in err


# --- list-findings hints (gate queries) -----------------------------------


def test_untriaged_count_positive_hint(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    _record(monkeypatch, initialized, capsys, message="m", file="x.py")
    run_cli(monkeypatch, initialized, "list-findings", "--triage=untriaged", "--count")
    captured = capsys.readouterr()
    assert captured.out.strip() == "1"
    assert "hint:" in captured.err
    assert "triage" in captured.err.lower()


def test_untriaged_count_zero_hint(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    run_cli(monkeypatch, initialized, "list-findings", "--triage=untriaged", "--count")
    captured = capsys.readouterr()
    assert captured.out.strip() == "0"
    assert "hint:" in captured.err
    assert "triage phase complete" in captured.err.lower()


def test_auto_open_count_hint(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    fid = _record(monkeypatch, initialized, capsys, message="m", file="x.py")
    _triage(monkeypatch, initialized, capsys, fid, "auto")
    run_cli(
        monkeypatch,
        initialized,
        "list-findings",
        "--triage=auto",
        "--status=open",
        "--count",
    )
    captured = capsys.readouterr()
    assert captured.out.strip() == "1"
    assert "hint:" in captured.err
    assert "auto-resolve" in captured.err.lower()


def test_interactive_open_count_hint(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    fid = _record(monkeypatch, initialized, capsys, message="m", file="x.py")
    _triage(monkeypatch, initialized, capsys, fid, "interactive")
    run_cli(
        monkeypatch,
        initialized,
        "list-findings",
        "--triage=interactive",
        "--status=open",
        "--count",
    )
    captured = capsys.readouterr()
    assert captured.out.strip() == "1"
    assert "hint:" in captured.err
    assert "interactive-resolve" in captured.err.lower()


def test_non_gate_query_no_hint(initialized: Path, monkeypatch, capsys):
    """A bare `list-findings --count` (no filters) isn't a known gate;
    don't emit a hint there."""
    _start(monkeypatch, initialized, capsys)
    run_cli(monkeypatch, initialized, "list-findings", "--count")
    err = capsys.readouterr().err
    assert "hint:" not in err


def test_list_findings_non_count_no_hint(initialized: Path, monkeypatch, capsys):
    """Fetching the actual list shouldn't emit a hint either — hints are for
    the gate-query (--count) form."""
    _start(monkeypatch, initialized, capsys)
    _record(monkeypatch, initialized, capsys, message="m", file="x.py")
    run_cli(monkeypatch, initialized, "list-findings", "--triage=untriaged")
    err = capsys.readouterr().err
    assert "hint:" not in err


# --- stdout purity --------------------------------------------------------


def test_stdout_remains_pure_integer(initialized: Path, monkeypatch, capsys):
    """A skill capturing `$(sqa-tool needs-review --count)` should get a
    parseable integer — the hint must not bleed into stdout."""
    out = capture_cli(capsys, monkeypatch, initialized, "needs-review", "--count")
    assert out.strip().isdigit()
