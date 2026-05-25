"""Tests for the shared fcntl-locked byte-level file I/O helper.

The two callers (file_status.py and result_file.py) have their own
end-to-end tests that incidentally exercise this module via their public
APIs. The tests here pin the helper's contract directly so a regression
in the shared layer surfaces as a focused test failure rather than as
mysterious behavior changes in two unrelated modules.
"""

import fcntl
import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from sqa_tool import _locked_file

# --- locked(): create_with semantics --------------------------------------


def test_locked_creates_with_seed_when_missing(tmp_path: Path):
    """create_with=bytes: file doesn't exist → opened with O_CREAT and
    seeded with the bytes under LOCK_EX."""
    path = tmp_path / "subdir" / "f.json"  # parent dir also missing
    assert not path.exists()
    with _locked_file.locked(path, create_with=b'{"x": 1}\n') as fd:
        # File exists now; content is the seed.
        assert path.exists()
        assert _locked_file.read_all(fd) == '{"x": 1}\n'
    # Persisted after the context exits.
    assert path.read_text() == '{"x": 1}\n'


def test_locked_raises_when_create_with_is_none_and_file_missing(tmp_path: Path):
    """create_with=None: missing file is an error, not a lazy-create case."""
    path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError, match="file does not exist"):
        with _locked_file.locked(path):
            pass  # never reached


def test_locked_preserves_existing_content_when_seed_passed(tmp_path: Path):
    """The seed is only written when the file is empty after lock
    acquisition. An existing-content file is left alone — the helper
    is never destructive."""
    path = tmp_path / "f.json"
    path.write_text('{"prior": "content"}\n')
    with _locked_file.locked(path, create_with=b'{"x": 1}\n') as fd:
        assert _locked_file.read_all(fd) == '{"prior": "content"}\n'
    assert path.read_text() == '{"prior": "content"}\n'


def test_locked_does_not_seed_under_lock_sh(tmp_path: Path):
    """Race-free init contract: even with create_with set, a LOCK_SH
    caller must not write the seed. Two concurrent shared-lock holders
    would otherwise both see an empty file and could race on writes;
    seeding under LOCK_EX only is what makes init safe."""
    path = tmp_path / "f.json"
    path.touch()  # exists, but empty (zero bytes)
    with _locked_file.locked(path, fcntl.LOCK_SH, create_with=b'{"x": 1}\n') as fd:
        # File is still empty inside the context — no seed write happened.
        assert _locked_file.read_all(fd) == ""
    # And remains empty on disk.
    assert path.read_text() == ""


def test_locked_seeds_empty_existing_file_under_lock_ex(tmp_path: Path):
    """An existing zero-byte file under LOCK_EX with create_with set
    *is* seeded — this is the "the file was created by O_CREAT but the
    seed write hasn't landed yet" branch the file_status init flow
    relies on."""
    path = tmp_path / "f.json"
    path.touch()  # exists, but zero bytes
    with _locked_file.locked(path, create_with=b"{}\n") as fd:
        assert _locked_file.read_all(fd) == "{}\n"
    assert path.read_text() == "{}\n"


# --- read_all / write_all --------------------------------------------------


def test_read_all_round_trip(tmp_path: Path):
    """write_all + read_all is a faithful UTF-8 round trip."""
    path = tmp_path / "f.txt"
    path.touch()
    payload = 'mixed: "ascii" plus snowman ☃ and emoji 🦀\n'
    with _locked_file.locked(path) as fd:
        _locked_file.write_all(fd, payload)
        assert _locked_file.read_all(fd) == payload
    assert path.read_text() == payload


def test_write_all_truncates_longer_existing_content(tmp_path: Path):
    """write_all replaces the entire file: a long pre-existing payload
    overwritten with a shorter one leaves no trailing bytes from the
    old content."""
    path = tmp_path / "f.txt"
    path.write_text("AAAAAAAAAAAAAAAAAAAA\n")  # 21 bytes
    with _locked_file.locked(path) as fd:
        _locked_file.write_all(fd, "B\n")  # 2 bytes
    assert path.read_text() == "B\n"
    assert path.stat().st_size == 2


# --- Lock acquisition (sanity check that flock is actually called) --------


def _hold_lock_briefly(path_str: str, hold_seconds: float, barrier) -> None:
    """Child process: acquire LOCK_EX, signal via barrier, hold for
    `hold_seconds`, release."""
    path = Path(path_str)
    barrier.wait()
    with _locked_file.locked(path):
        # Signal that we've acquired the lock.
        time.sleep(hold_seconds)


@pytest.mark.skipif(
    "fork" not in mp.get_all_start_methods(),
    reason="fcntl test requires POSIX fork()",
)
def test_locked_actually_serializes_across_processes(tmp_path: Path):
    """Sanity check that the helper's flock call really is enforced
    across processes — protects against an accidental
    `LOCK_NB`/no-op refactor that would make the wrapper look like it
    locks without actually doing so."""
    path = tmp_path / "shared.json"
    path.write_text("{}\n")
    ctx = mp.get_context("fork")
    barrier = ctx.Barrier(1)
    # Hold the lock from a child for 0.5 seconds; verify a same-process
    # acquire in the parent blocks until release.
    child = ctx.Process(target=_hold_lock_briefly, args=(str(path), 0.5, barrier))
    child.start()
    barrier.wait()  # both sides at the same point; child is about to lock
    # Give the child time to actually acquire the lock before we try.
    time.sleep(0.05)

    t0 = time.monotonic()
    with _locked_file.locked(path):
        elapsed = time.monotonic() - t0
    child.join(timeout=2)
    assert not child.is_alive()
    # Parent's acquire should have blocked until the child released
    # (~0.45s remaining after the 0.05s warm-up sleep). Allow generous
    # slack to avoid flakiness, but require non-trivial wait so a no-op
    # lock would fail this assertion.
    assert elapsed > 0.2, f"parent acquired in {elapsed:.3f}s — lock didn't serialize against child"


def test_locked_releases_on_exception(tmp_path: Path):
    """The context manager must release the lock even when the body
    raises — otherwise a single failure would deadlock all subsequent
    callers in the same process."""
    path = tmp_path / "f.json"
    path.write_text("{}\n")

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with _locked_file.locked(path):
            raise Boom()

    # If the lock had leaked, the next acquire would deadlock. The fact
    # that this second `with` completes proves release-on-exception.
    with _locked_file.locked(path) as fd:
        assert _locked_file.read_all(fd) == "{}\n"


# --- File-descriptor cleanup ----------------------------------------------


def test_locked_closes_fd_on_normal_exit(tmp_path: Path):
    """The yielded fd is closed on context exit so callers don't leak
    file descriptors. Verifies by capturing the fd and asserting that
    it's invalid after the block."""
    path = tmp_path / "f.json"
    path.write_text("{}\n")
    captured_fd = None
    with _locked_file.locked(path) as fd:
        captured_fd = fd
    # After exit, the fd should be closed — any operation on it should
    # raise OSError (typically EBADF).
    with pytest.raises(OSError):
        os.fstat(captured_fd)
