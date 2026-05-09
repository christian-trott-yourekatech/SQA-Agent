"""Path helpers for the sqa project tree."""

from pathlib import Path

SQA_DIR_NAME = ".sqa"
FINDINGS_DIR_NAME = "findings"
FILE_STATUS_NAME = "file_status.json"
CONFIG_NAME = "config.toml"
SCOPE_FILE_NAME = ".sqa.md"


def sqa_dir(project_root: Path) -> Path:
    """Return the .sqa/ directory for a project root (may not exist)."""
    return project_root / SQA_DIR_NAME


def findings_dir(project_root: Path) -> Path:
    return sqa_dir(project_root) / FINDINGS_DIR_NAME


def file_status_path(project_root: Path) -> Path:
    return sqa_dir(project_root) / FILE_STATUS_NAME


def config_path(project_root: Path) -> Path:
    return sqa_dir(project_root) / CONFIG_NAME


def finding_path(project_root: Path, finding_id: str) -> Path:
    return findings_dir(project_root) / f"{finding_id}.json"
