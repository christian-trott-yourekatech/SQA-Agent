"""Tests for the per-session lifecycle CLI commands: start-result,
active-result, categories."""

from pathlib import Path

from conftest import capture_cli, run_cli

from sqa_tool import paths
from sqa_tool.result_file import active_result_path, list_result_paths

# --- categories -----------------------------------------------------------


def test_categories_prints_default_list(initialized: Path, monkeypatch, capsys):
    out = capture_cli(capsys, monkeypatch, initialized, "categories")
    lines = out.strip().splitlines()
    # init writes config.toml with the default list, so we expect those names.
    assert "logic" in lines
    assert "security" in lines
    assert "error-handling" in lines


def test_categories_respects_config(initialized: Path, monkeypatch, capsys):
    cfg = paths.config_path(initialized)
    cfg.write_text('[files]\ninclude = []\nexclude = []\n[categories]\nlist = ["alpha", "beta"]\n')
    out = capture_cli(capsys, monkeypatch, initialized, "categories")
    assert out.strip().splitlines() == ["alpha", "beta"]


# --- start-result ---------------------------------------------------------


def test_start_result_creates_file(initialized: Path, monkeypatch, capsys):
    out = capture_cli(capsys, monkeypatch, initialized, "start-result")
    lines = out.strip().splitlines()
    path = Path(lines[0])
    assert path.exists()
    assert path.name.startswith("result_") and path.name.endswith(".json")
    assert lines[1].startswith("Categories:")


def test_start_result_includes_categories_line(initialized: Path, monkeypatch, capsys):
    out = capture_cli(capsys, monkeypatch, initialized, "start-result")
    cat_line = out.strip().splitlines()[1]
    # All default categories should appear in the comma-separated list.
    for name in ("logic", "security", "error-handling"):
        assert name in cat_line


def test_start_result_creates_new_each_time(initialized: Path, monkeypatch, capsys):
    """Successive starts produce distinct files (we can't easily test the
    same-second collision here without time-mocking the CLI; the unit test in
    test_result_file.py covers that path. This guards the typical case)."""
    capture_cli(capsys, monkeypatch, initialized, "start-result")
    # Force the second start to land in a different second.
    import time

    time.sleep(1.05)
    capture_cli(capsys, monkeypatch, initialized, "start-result")
    sqa = paths.sqa_dir(initialized)
    assert len(list_result_paths(sqa)) == 2


# --- active-result --------------------------------------------------------


def test_active_result_with_no_session_errors(initialized: Path, monkeypatch):
    run_cli(monkeypatch, initialized, "active-result", expected_exit=1)


def test_active_result_returns_most_recent(initialized: Path, monkeypatch, capsys):
    capture_cli(capsys, monkeypatch, initialized, "start-result")
    out = capture_cli(capsys, monkeypatch, initialized, "active-result")
    sqa = paths.sqa_dir(initialized)
    expected = active_result_path(sqa)
    assert out.strip() == str(expected)


def test_active_result_tracks_latest_after_second_start(initialized: Path, monkeypatch, capsys):
    import time

    capture_cli(capsys, monkeypatch, initialized, "start-result")
    time.sleep(1.05)
    second_out = capture_cli(capsys, monkeypatch, initialized, "start-result")
    second_path = Path(second_out.strip().splitlines()[0])
    active_out = capture_cli(capsys, monkeypatch, initialized, "active-result")
    assert active_out.strip() == str(second_path)


def test_start_result_refuses_when_prior_session_has_open_findings(
    initialized: Path, monkeypatch, capsys
):
    """A wayward subagent calling start-result during an in-progress
    session is the failure mode this guard catches: a CLI-level error
    surface keeps the active result intact."""
    capture_cli(capsys, monkeypatch, initialized, "start-result")
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=in-progress",
        "--file=src/sample.py",
    )
    # Without --force, a second start-result is refused.
    run_cli(monkeypatch, initialized, "start-result", expected_exit=1)
    err = capsys.readouterr().err
    assert "unresolved" in err
    assert "--force" in err


def test_start_result_force_bypasses_guard(initialized: Path, monkeypatch, capsys):
    """The legitimate "abandoned last session, want fresh" case is unblocked
    by --force."""
    import time

    capture_cli(capsys, monkeypatch, initialized, "start-result")
    capture_cli(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=abandoned",
        "--file=src/sample.py",
    )
    time.sleep(1.05)
    capture_cli(capsys, monkeypatch, initialized, "start-result", "--force")
    # Active result now points at the new file, which is empty.
    sqa = paths.sqa_dir(initialized)
    paths_list = list_result_paths(sqa)
    assert len(paths_list) == 2
