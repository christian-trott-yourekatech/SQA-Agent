"""fcntl-locked read-modify-write of .sqa/file_status.json."""

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator
from pathlib import Path

from sqa_tool import paths


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[int]:
    """Acquire an exclusive fcntl lock on `path`. Creates it if missing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}\n")
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def load(project_root: Path) -> dict[str, str]:
    """Load the file_status mapping (rel_path → blob hash)."""
    path = paths.file_status_path(project_root)
    if not path.exists():
        return {}
    with open(path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Corrupt file_status at {path}: {e}") from None


def save(project_root: Path, status: dict[str, str]) -> None:
    """Replace the file_status content under fcntl lock."""
    path = paths.file_status_path(project_root)
    with _locked(path):
        path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")


def update(project_root: Path, rel_path: str, blob_hash: str) -> None:
    """Update one entry under lock (read-modify-write)."""
    path = paths.file_status_path(project_root)
    with _locked(path) as fd:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, os.fstat(fd).st_size).decode() or "{}"
        try:
            status: dict[str, str] = json.loads(raw)
        except json.JSONDecodeError:
            status = {}
        status[rel_path] = blob_hash
        new_text = json.dumps(status, indent=2, sort_keys=True) + "\n"
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, new_text.encode())


def remove(project_root: Path, rel_path: str) -> None:
    """Remove one entry under lock."""
    path = paths.file_status_path(project_root)
    with _locked(path) as fd:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, os.fstat(fd).st_size).decode() or "{}"
        try:
            status: dict[str, str] = json.loads(raw)
        except json.JSONDecodeError:
            status = {}
        status.pop(rel_path, None)
        new_text = json.dumps(status, indent=2, sort_keys=True) + "\n"
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, new_text.encode())
