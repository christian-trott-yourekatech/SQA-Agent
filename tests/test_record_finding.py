"""Tests for the v2.1 record-finding command."""

from pathlib import Path

from conftest import capture_cli, run_cli

from sqa_tool import paths
from sqa_tool.result_file import Finding, active_result_path, load_result


def _start(monkeypatch, project: Path, capsys) -> Path:
    """Start a fresh result file; return its path."""
    out = capture_cli(capsys, monkeypatch, project, "start-result")
    return Path(out.strip().splitlines()[0])


def _load_active(project: Path) -> list[Finding]:
    """Load the active result file, asserting one exists (helps the type
    checker; tests in this file always have an active result by the time
    they call this)."""
    sqa = paths.sqa_dir(project)
    path = active_result_path(sqa)
    assert path is not None, "expected an active result file"
    return load_result(path)


def test_record_finding_basic(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    out = capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=raise Exception is too broad",
        "--file=src/sample.py",
        "--line=2",
        "--quoted-text=raise Exception",
        "--category=error-handling",
        "--severity=warning",
    )
    new_id = int(out.strip())
    assert new_id == 1

    findings = _load_active(initialized)
    assert len(findings) == 1
    f = findings[0]
    assert f.id == 1
    assert f.message == "raise Exception is too broad"
    assert f.file == "src/sample.py"
    assert f.line == 2
    assert f.quoted_text == "raise Exception"
    assert f.category == "error-handling"
    assert f.severity == "warning"
    assert f.triage is None
    assert f.status == "open"


def test_record_finding_project_wide(initialized: Path, monkeypatch, capsys):
    """No --file → project-wide finding."""
    _start(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=missing CONTRIBUTING.md",
        "--category=project-specific",
    )
    f = _load_active(initialized)[0]
    assert f.file is None
    assert f.line is None


def test_record_finding_with_related(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=DRY violation across files",
        "--file=src/sample.py",
        "--related=src/other.py",
        "--related=src/another.py",
        "--category=dry-ssot",
    )
    f = _load_active(initialized)[0]
    assert f.related == ["src/other.py", "src/another.py"]


def test_record_finding_sequential_ids(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    a = capture_cli(
        capsys, monkeypatch, initialized, "record-finding", "--message=a", "--file=src/sample.py"
    ).strip()
    b = capture_cli(
        capsys, monkeypatch, initialized, "record-finding", "--message=b", "--file=src/sample.py"
    ).strip()
    assert (a, b) == ("1", "2")


def test_record_finding_no_active_result_errors(initialized: Path, monkeypatch, capsys):
    """No `start-result` yet → record-finding refuses with a pointer."""
    run_cli(
        monkeypatch,
        initialized,
        "record-finding",
        "--message=anything",
        "--file=src/sample.py",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "start-result" in err


def test_record_finding_line_requires_file(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    run_cli(
        monkeypatch,
        initialized,
        "record-finding",
        "--message=x",
        "--line=10",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "require --file" in err


def test_record_finding_quoted_text_requires_file(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    run_cli(
        monkeypatch,
        initialized,
        "record-finding",
        "--message=x",
        "--quoted-text=foo",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "require --file" in err


def test_record_finding_unknown_category_warns(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    run_cli(
        monkeypatch,
        initialized,
        "record-finding",
        "--message=x",
        "--file=src/sample.py",
        "--category=made-up-category",
    )
    err = capsys.readouterr().err
    assert "made-up-category" in err
    assert "not in configured list" in err
    # …but the finding is still recorded.
    assert len(_load_active(initialized)) == 1


def test_record_finding_known_category_silent(initialized: Path, monkeypatch, capsys):
    _start(monkeypatch, initialized, capsys)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=x",
        "--file=src/sample.py",
        "--category=logic",
    )
    err = capsys.readouterr().err
    assert "not in configured list" not in err


def _resolve_finding_via_api(result_path: Path, finding_id: int) -> None:
    """Bypass the CLI to put a finding into a resolved state, so the
    record-finding safety guard can be tested in isolation from the v2 →
    v2.1 triage rewrite (migration plan item 5)."""
    from sqa_tool.result_file import apply_triage, find_by_id, with_locked_result

    with with_locked_result(result_path) as (_, findings):
        apply_triage(find_by_id(findings, finding_id), "ignore", "test-resolved")


def test_record_finding_safety_guard_blocks_after_resolve(initialized: Path, monkeypatch, capsys):
    """Once any finding is resolved, record-finding refuses without --force."""
    result_path = _start(monkeypatch, initialized, capsys)
    fid = int(
        capture_cli(
            capsys,
            monkeypatch,
            initialized,
            "record-finding",
            "--message=x",
            "--file=src/sample.py",
        ).strip()
    )
    _resolve_finding_via_api(result_path, fid)
    run_cli(
        monkeypatch,
        initialized,
        "record-finding",
        "--message=second",
        "--file=src/sample.py",
        expected_exit=1,
    )
    err = capsys.readouterr().err
    assert "already has resolved findings" in err


def test_record_finding_force_bypasses_safety_guard(initialized: Path, monkeypatch, capsys):
    result_path = _start(monkeypatch, initialized, capsys)
    fid = int(
        capture_cli(
            capsys,
            monkeypatch,
            initialized,
            "record-finding",
            "--message=x",
            "--file=src/sample.py",
        ).strip()
    )
    _resolve_finding_via_api(result_path, fid)
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=second",
        "--file=src/sample.py",
        "--force",
    )
    assert len(_load_active(initialized)) == 2
