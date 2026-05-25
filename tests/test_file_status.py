"""Tests for the fcntl-locked file_status module."""

import json
import multiprocessing as mp
import time
from pathlib import Path

import pytest

from sqa_tool import file_status, paths

# Shared parametrize list of the module's three public entry points. Used by
# the corruption- and wrong-shape-surfacing tests below so adding a fourth
# public entry point only requires editing one list and the two tests stay
# in lockstep by construction.
PUBLIC_ENTRY_POINTS = [
    pytest.param(lambda p: file_status.load(p), id="load"),
    pytest.param(lambda p: file_status.update(p, "src/a.py", "h1"), id="update"),
    pytest.param(lambda p: file_status.remove(p, "src/anything.py"), id="remove"),
]


def test_load_empty(initialized: Path):
    assert file_status.load(initialized) == {}


def test_update_creates_entry(initialized: Path):
    file_status.update(initialized, "src/foo.py", "abc123")
    assert file_status.load(initialized) == {"src/foo.py": "abc123"}


def test_update_replaces_entry(initialized: Path):
    file_status.update(initialized, "src/foo.py", "abc123")
    file_status.update(initialized, "src/foo.py", "def456")
    assert file_status.load(initialized) == {"src/foo.py": "def456"}


def test_multiple_entries(initialized: Path):
    file_status.update(initialized, "src/a.py", "h1")
    file_status.update(initialized, "src/b.py", "h2")
    file_status.update(initialized, "src/c.py", "h3")
    assert file_status.load(initialized) == {
        "src/a.py": "h1",
        "src/b.py": "h2",
        "src/c.py": "h3",
    }


def test_remove(initialized: Path):
    file_status.update(initialized, "src/a.py", "h1")
    file_status.update(initialized, "src/b.py", "h2")
    file_status.remove(initialized, "src/a.py")
    assert file_status.load(initialized) == {"src/b.py": "h2"}


def test_persisted_format_is_json(initialized: Path):
    # Write two entries in reverse-sorted insertion order so sort_keys=True is
    # observable in the serialized form (single-entry payloads can't witness it).
    file_status.update(initialized, "b.py", "hash_b")
    file_status.update(initialized, "a.py", "hash_a")
    raw = paths.file_status_path(initialized).read_text()
    assert json.loads(raw) == {"a.py": "hash_a", "b.py": "hash_b"}
    # Pin the deterministic-format contract _write_locked deliberately produces
    # (indent=2, sort_keys=True, trailing newline) so file_status.json stays
    # diff-clean under version control / human inspection.
    assert raw.endswith("\n"), "persisted file_status must end with a trailing newline"
    assert raw.index('"a.py"') < raw.index('"b.py"'), "keys must be sorted"
    assert '\n  "' in raw, "persisted file_status must use indent=2"


def test_remove_missing_key_is_noop(initialized: Path):
    file_status.update(initialized, "src/a.py", "h1")
    file_status.remove(initialized, "src/does_not_exist.py")
    assert file_status.load(initialized) == {"src/a.py": "h1"}


def test_remove_on_empty_store_is_noop(initialized: Path):
    file_status.remove(initialized, "src/missing.py")
    assert file_status.load(initialized) == {}


def test_remove_on_missing_file_is_noop(initialized: Path):
    status_path = paths.file_status_path(initialized)
    status_path.unlink()
    file_status.remove(initialized, "src/missing.py")
    assert file_status.load(initialized) == {}
    # No-op refers to the observable load() result. Filesystem-side, remove()
    # acquires _locked() which opens with O_CREAT and seeds '{}' under LOCK_EX,
    # so the status file is recreated as an empty JSON object.
    assert status_path.exists(), (
        "remove() should recreate the status file via O_CREAT under the lock"
    )


def test_load_on_missing_file_returns_empty(initialized: Path):
    status_path = paths.file_status_path(initialized)
    status_path.unlink()
    assert file_status.load(initialized) == {}


def test_load_on_zero_byte_file_returns_empty(initialized: Path):
    """Guards the empty-string branch in load() that handles a LOCK_SH reader
    racing a first-time writer between O_CREAT and the initial _write_locked.
    """
    status_path = paths.file_status_path(initialized)
    status_path.write_text("")
    assert file_status.load(initialized) == {}


def _child_updates(project_root_str: str, prefix: str, count: int, barrier) -> None:
    project = Path(project_root_str)
    barrier.wait()  # all children release together → contention guaranteed
    for i in range(count):
        file_status.update(project, f"{prefix}/file_{i}.py", f"hash_{prefix}_{i}")


@pytest.mark.skipif(
    "fork" not in mp.get_all_start_methods(),
    reason="fcntl test requires POSIX fork()",
)
def test_concurrent_processes_no_lost_writes(initialized: Path):
    """fcntl serializes writes across processes — every write from every
    child must land in the merged file. Threads can't substitute here: per
    flock(2), separate fds in the same process can both hold LOCK_EX, so a
    thread-based test would only prove GIL serialization, not the contract
    the module exists to provide (safe RMW across parallel subagent
    processes). Pinned to the 'fork' start method so the contract being
    tested is unambiguous and stable across OS/Python versions (Python 3.14
    moved macOS away from fork by default).
    """
    n_processes = 4
    updates_per_process = 25
    ctx = mp.get_context("fork")
    barrier = ctx.Barrier(n_processes)
    procs = [
        ctx.Process(
            target=_child_updates,
            args=(str(initialized), f"proc{i}", updates_per_process, barrier),
        )
        for i in range(n_processes)
    ]
    for p in procs:
        p.start()
    # Single 30s deadline shared across all joins so a deadlock bounds total
    # wait at ~30s regardless of n_processes (per-child timeouts would compound
    # to n*30s worst-case).
    deadline = time.monotonic() + 30
    for p in procs:
        p.join(timeout=max(0.0, deadline - time.monotonic()))
    for p in procs:
        if p.is_alive():
            # Don't let a hung child leak past the test and chew up CI resources.
            p.terminate()
            p.join(timeout=5)
        assert not p.is_alive(), f"child {p.pid} survived deadline join and SIGTERM"
    for p in procs:
        assert p.exitcode == 0, f"child failed with exit {p.exitcode}"

    status = file_status.load(initialized)
    assert len(status) == n_processes * updates_per_process
    for proc_id in range(n_processes):
        for i in range(updates_per_process):
            key = f"proc{proc_id}/file_{i}.py"
            assert key in status, f"missing {key} — write lost during concurrent update"
            assert status[key] == f"hash_proc{proc_id}_{i}"


@pytest.mark.parametrize("call", PUBLIC_ENTRY_POINTS)
def test_public_entry_points_surface_corruption(initialized: Path, call):
    """Every public entry point must raise RuntimeError on corrupt JSON."""
    status_path = paths.file_status_path(initialized)
    status_path.write_text("{not valid json")
    # The "Corrupt file_status" literal is intentionally duplicated here rather
    # than shared with file_status._parse_status via a constant: this test pins
    # the user-visible error-message prefix as part of the public contract.
    # Importing the constant would mean a rename in production silently updates
    # the assertion, hiding exactly the contract drift this test exists to catch.
    with pytest.raises(RuntimeError, match="Corrupt file_status"):
        call(initialized)


@pytest.mark.parametrize(
    ("raw", "expected_msg_substring"),
    [
        # Top-level must be a JSON object — these are valid JSON but the
        # wrong shape, the case where downstream update()/remove() would
        # otherwise crash with a cryptic TypeError instead of a clean
        # corruption error.
        pytest.param("[]", "expected JSON object", id="top-level-list"),
        pytest.param('"foo"', "expected JSON object", id="top-level-string"),
        pytest.param("123", "expected JSON object", id="top-level-int"),
        pytest.param("null", "expected JSON object", id="top-level-null"),
        # Dict shape with non-string values — silently wrong reads would
        # mis-compare against fresh git hashes.
        pytest.param('{"x": 1}', "every value must be a string", id="int-value"),
        pytest.param('{"x": null}', "every value must be a string", id="null-value"),
        pytest.param('{"x": [1, 2]}', "every value must be a string", id="list-value"),
        pytest.param('{"x": {"nested": true}}', "every value must be a string", id="dict-value"),
    ],
)
def test_load_raises_on_wrong_shape(initialized: Path, raw, expected_msg_substring):
    """file_status.json must deserialize to ``dict[str, str]``. Any other
    shape is corruption; surface the same clean RuntimeError that malformed
    JSON produces rather than letting downstream operations propagate a
    cryptic TypeError."""
    status_path = paths.file_status_path(initialized)
    status_path.write_text(raw)
    with pytest.raises(RuntimeError, match="Corrupt file_status") as exc:
        file_status.load(initialized)
    assert expected_msg_substring in str(exc.value)


@pytest.mark.parametrize("call", PUBLIC_ENTRY_POINTS)
def test_public_entry_points_surface_wrong_shape(initialized: Path, call):
    """The shape-validation error must propagate through every public entry
    point, not just load() — mirrors the JSON-corruption test above so a
    hand-edit caught at update/remove time produces the same clean error
    as at load time."""
    status_path = paths.file_status_path(initialized)
    status_path.write_text("[]")  # representative wrong-shape case
    with pytest.raises(RuntimeError, match="Corrupt file_status"):
        call(initialized)
