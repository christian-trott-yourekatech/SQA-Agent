"""Shared fixtures: a temp project that's a real git repo with .sqa/ initialized."""

import subprocess
from pathlib import Path

import pytest


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


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

    cwd_save = Path.cwd()
    import os

    os.chdir(project)
    try:
        init_run(project)
    finally:
        os.chdir(cwd_save)
    return project
