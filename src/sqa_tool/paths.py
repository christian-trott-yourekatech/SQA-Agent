"""Path helpers for the sqa project tree."""

from pathlib import Path

SQA_DIR_NAME = ".sqa"
GIT_DIR_NAME = ".git"
FILE_STATUS_NAME = "file_status.json"
CONFIG_NAME = "config.toml"


def sqa_dir(project_root: Path) -> Path:
    """Return the .sqa/ directory for a project root (may not exist)."""
    return project_root / SQA_DIR_NAME


def file_status_path(project_root: Path) -> Path:
    return sqa_dir(project_root) / FILE_STATUS_NAME


def config_path(project_root: Path) -> Path:
    return sqa_dir(project_root) / CONFIG_NAME
