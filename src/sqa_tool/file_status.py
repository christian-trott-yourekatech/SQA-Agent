"""fcntl-locked read-modify-write of .sqa/file_status.json."""

import contextlib
import fcntl
import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

from sqa_tool import paths


@contextlib.contextmanager
def _locked(path: Path, lock_op: int = fcntl.LOCK_EX) -> Iterator[int]:
    """Acquire an fcntl lock on `path`. Creates the file if missing (race-free).

    `lock_op` is `fcntl.LOCK_EX` (writers) or `fcntl.LOCK_SH` (readers).
    Initializes empty files with '{}\\n' only after the lock is held, so
    concurrent first-use callers can't clobber each other's init.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, lock_op)
        if os.fstat(fd).st_size == 0 and lock_op == fcntl.LOCK_EX:
            os.write(fd, b"{}\n")
            os.lseek(fd, 0, os.SEEK_SET)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_all(fd: int) -> str:
    """Seek to start and read the entire file from `fd`, decoded as UTF-8."""
    os.lseek(fd, 0, os.SEEK_SET)
    return os.read(fd, os.fstat(fd).st_size).decode()


def load(project_root: Path) -> dict[str, str]:
    """Load the file_status mapping (rel_path → blob hash).

    Returns `{}` if the file is missing or empty. Empty-file handling
    matters because `_locked` only seeds `{}` under `LOCK_EX`; a `LOCK_SH`
    reader observing a zero-byte file (e.g. between `O_CREAT` and the
    first writer's `_write_locked`) would otherwise feed an empty string
    to `_parse_status` and trip a JSON-decode error.
    """
    path = paths.file_status_path(project_root)
    if not path.exists():
        return {}
    with _locked(path, fcntl.LOCK_SH) as fd:
        raw = _read_all(fd)
        if raw == "":
            return {}
        return _parse_status(raw, path)


def _parse_status(raw: str, path: Path) -> dict[str, str]:
    """Parse the locked file's contents, raising on malformed JSON."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Corrupt file_status at {path}: {e}") from e


def _write_locked(fd: int, status: dict[str, str]) -> None:
    """Write `status` as JSON through the already-locked fd."""
    new_text = json.dumps(status, indent=2, sort_keys=True) + "\n"
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, new_text.encode())


def _mutate(project_root: Path, fn: Callable[[dict[str, str]], None]) -> None:
    """Run a locked read-modify-write cycle, applying `fn` to the dict in place."""
    path = paths.file_status_path(project_root)
    with _locked(path) as fd:
        status = _parse_status(_read_all(fd), path)
        fn(status)
        _write_locked(fd, status)


def update(project_root: Path, rel_path: str, blob_hash: str) -> None:
    """Update one entry under lock (read-modify-write)."""
    _mutate(project_root, lambda status: status.__setitem__(rel_path, blob_hash))


def remove(project_root: Path, rel_path: str) -> None:
    """Remove one entry under lock."""

    def _pop(status: dict[str, str]) -> None:
        status.pop(rel_path, None)

    _mutate(project_root, _pop)
