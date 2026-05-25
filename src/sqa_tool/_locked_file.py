"""fcntl-locked byte-level file I/O shared by :mod:`sqa_tool.file_status`
and :mod:`sqa_tool.result_file`.

Both modules layer different parse/serialize logic on top of the same
underlying pattern: open under fcntl lock, read bytes, modify, write
bytes. This module owns the byte-level lock/read/write primitives so
locking semantics can't drift between callers; the JSON shape and
dataclass mapping stay in each caller because those genuinely differ
(flat ``dict[str, str]`` vs. the versioned result-file schema).

Internal to sqa_tool — the leading underscore on the module name marks
it as not part of any external surface.
"""

import contextlib
import fcntl
import os
from collections.abc import Iterator
from pathlib import Path


@contextlib.contextmanager
def locked(
    path: Path,
    lock_op: int = fcntl.LOCK_EX,
    *,
    create_with: bytes | None = None,
) -> Iterator[int]:
    """Acquire an fcntl lock on ``path``; yield the file descriptor.

    ``lock_op`` is ``fcntl.LOCK_EX`` (writers) or ``fcntl.LOCK_SH``
    (readers).

    ``create_with`` selects between the two file-existence policies the
    two callers need:

      * ``None`` (default): the file must already exist. Raises
        ``FileNotFoundError`` if not. Use when missing-file is an error
        in context (e.g. the result file that should have been created
        by ``start-result``).
      * ``bytes``: open with ``O_CREAT`` (creating the parent directory
        if needed). If the file is empty after lock acquisition AND we
        hold ``LOCK_EX``, write these bytes as the initial content. Use
        for indexes that should be lazily created on first use (e.g.
        ``file_status.json`` with seed ``b'{}\\n'``).

    Race-free init contract: the seed write only happens under
    ``LOCK_EX``. Two concurrent first-use callers each acquire the
    exclusive lock in turn — only the first one's ``fstat`` sees size
    zero, so only it writes the seed; the second one's ``fstat`` sees
    the seed already in place and skips. A ``LOCK_SH`` reader observing
    a zero-byte file (because no writer has run yet) must handle empty
    content itself — this helper deliberately does *not* write under a
    shared lock, since shared-lock holders by definition can't claim
    exclusive write access to the file.
    """
    if create_with is None:
        if not path.exists():
            raise FileNotFoundError(f"file does not exist: {path}")
        fd = os.open(path, os.O_RDWR)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, lock_op)
        if create_with is not None and lock_op == fcntl.LOCK_EX and os.fstat(fd).st_size == 0:
            os.write(fd, create_with)
            os.lseek(fd, 0, os.SEEK_SET)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_all(fd: int) -> str:
    """Seek to start and read the entire file from ``fd``, decoded as UTF-8."""
    os.lseek(fd, 0, os.SEEK_SET)
    return os.read(fd, os.fstat(fd).st_size).decode()


def write_all(fd: int, text: str) -> None:
    """Truncate ``fd`` and write ``text`` encoded as UTF-8.

    The seek-then-truncate-then-write sequence is the small detail that
    makes "replace entire file contents" safe under a held lock: an
    in-progress reader holding ``LOCK_SH`` is blocked until we release,
    so they can't observe the truncated-but-not-yet-written intermediate
    state. Without the lock (e.g. an unlocked external reader), the
    intermediate state is observable and the file may parse as empty
    JSON briefly — that's why every reader in the codebase acquires
    ``LOCK_SH`` rather than skipping the lock.
    """
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, text.encode())
