"""Shared fixtures: a temp project that's a real git repo with .sqa/ initialized."""

import subprocess
from pathlib import Path

import pytest

from sqa_tool.cli import main as cli_main
from sqa_tool.commands.init import run as init_run


def _git(cwd: Path, *args: str) -> None:
    try:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        stdout = e.stdout.decode(errors="replace") if e.stdout else ""
        cmd = " ".join(args)
        raise RuntimeError(
            f"git {cmd} failed (exit {e.returncode}):\nstderr: {stderr}\nstdout: {stdout}"
        ) from e


def _commit(project: Path, msg: str = "x") -> None:
    """Stage everything and create a commit. Throwaway-message convenience for tests."""
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", msg)


def run_cli(
    monkeypatch: pytest.MonkeyPatch, project: Path, *argv: str, expected_exit: int = 0
) -> int:
    # monkeypatch.chdir is per-test scoped and unwinds automatically — safe under
    # parallel runners (pytest-xdist) where process-global os.chdir would race.
    monkeypatch.chdir(project)
    # Some handlers exit via sys.exit() rather than returning an int (e.g.
    # the shared read-side error path), so catch SystemExit and treat its
    # code as the exit code. None/missing code is treated as 0 per Python.
    try:
        rc = cli_main(list(argv))
    except SystemExit as e:
        code = e.code
        rc = 0 if code is None else int(code)
    assert rc == expected_exit, f"sqa-tool {' '.join(argv)} exited {rc}"
    return rc


def capture_cli(
    capsys,
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    *argv: str,
    expected_exit: int = 0,
) -> str:
    """Run sqa-tool and return its captured stdout. Drains any prior buffered output first."""
    capsys.readouterr()
    run_cli(monkeypatch, project, *argv, expected_exit=expected_exit)
    return capsys.readouterr().out


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """Create a fresh git repo with one tracked file. Caller can run `sqa-tool init`."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    (tmp_path / "src").mkdir()
    sample = tmp_path / "src" / "sample.py"
    sample.write_text("def hello():\n    return 'world'\n")
    _commit(tmp_path, "initial")
    return tmp_path


@pytest.fixture
def initialized(project: Path) -> Path:
    """Project with sqa-tool init already run."""
    init_run(project)
    return project


@pytest.fixture
def configured(initialized: Path) -> Path:
    """Initialized project with .sqa/config.toml seeded to include src/**/*.py.

    Convenience for needs-review tests that want the sample src file picked
    up by the default include glob.
    """
    cfg = initialized / ".sqa" / "config.toml"
    cfg.write_text('[files]\ninclude = ["src/**/*.py"]\nexclude = []\n')
    return initialized
