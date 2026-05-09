"""Shared fixtures: a temp project that's a real git repo with .sqa/ initialized."""

import os
import subprocess
from pathlib import Path

import pytest

from sqa_tool.cli import main as cli_main


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _run(project: Path, *argv: str, expected_exit: int = 0) -> int:
    cwd = Path.cwd()
    os.chdir(project)
    try:
        rc = cli_main(list(argv))
    finally:
        os.chdir(cwd)
    assert rc == expected_exit, f"sqa-tool {' '.join(argv)} exited {rc}"
    return rc


def _capture(capsys, project: Path, *argv: str, expected_exit: int = 0) -> str:
    """Run sqa-tool and return its captured stdout. Drains any prior buffered output first."""
    capsys.readouterr()
    _run(project, *argv, expected_exit=expected_exit)
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
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "initial")
    return tmp_path


@pytest.fixture
def initialized(project: Path) -> Path:
    """Project with sqa-tool init already run."""
    from sqa_tool.commands.init import run as init_run

    init_run(project)
    return project
