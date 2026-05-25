"""Tests for the per-run result-file storage module."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sqa_tool import result_file
from sqa_tool.result_file import (
    Finding,
    StateTransitionError,
    UnresolvedFindingsError,
    active_result_path,
    add_finding,
    apply_resolve,
    apply_triage,
    find_by_id,
    findings_for_file,
    has_any_resolved,
    is_active,
    list_result_paths,
    load_result,
    make_result_path,
    next_id,
    resolve_from_argument,
    select_result,
    start_result,
    with_locked_result,
)

# --- Helpers ---------------------------------------------------------------


@pytest.fixture
def sqa_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".sqa"
    d.mkdir()
    return d


def _stamps_seconds_apart(n: int, start: datetime | None = None) -> list[datetime]:
    """N timestamps one second apart — used to deterministically order
    result files (filenames are second-granular)."""
    base = start or datetime(2026, 5, 24, 12, 0, 0)
    return [base + timedelta(seconds=i) for i in range(n)]


# --- start_result / active_result_path / list_result_paths ----------------


def test_start_result_creates_empty_file(sqa_dir: Path):
    path = start_result(sqa_dir)
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["version"] == 2
    assert data["findings"] == []
    assert data["total"] == 0
    assert data["timestamp"]  # non-empty


def test_active_is_none_when_no_results(sqa_dir: Path):
    assert active_result_path(sqa_dir) is None


def test_active_is_most_recent(sqa_dir: Path):
    a, b, c = _stamps_seconds_apart(3)
    pa = start_result(sqa_dir, a)
    pb = start_result(sqa_dir, b)
    pc = start_result(sqa_dir, c)
    assert active_result_path(sqa_dir) == pc
    assert list_result_paths(sqa_dir) == [pa, pb, pc]


def test_start_result_collides_same_second(sqa_dir: Path):
    """Two start_result calls within the same second raise — we'd rather
    surface than silently overwrite a freshly created sibling."""
    t = datetime(2026, 5, 24, 12, 0, 0)
    start_result(sqa_dir, t)
    with pytest.raises(FileExistsError):
        start_result(sqa_dir, t, force=True)


def test_start_result_refuses_when_prior_has_open_findings(sqa_dir: Path):
    """The safety guard: a wayward subagent calling start-result while
    review or resolve is in progress shouldn't be able to rotate the
    active pointer out from under everybody."""
    a, b = _stamps_seconds_apart(2)
    first = start_result(sqa_dir, a)
    with with_locked_result(first) as (_, findings):
        add_finding(findings, Finding(message="open finding", file="x.py"))
    with pytest.raises(UnresolvedFindingsError, match="unresolved"):
        start_result(sqa_dir, b)


def test_start_result_allowed_when_prior_fully_resolved(sqa_dir: Path):
    """When everything from the prior session is resolved, a new
    start-result is the legitimate "next session" — proceeds without
    --force."""
    a, b = _stamps_seconds_apart(2)
    first = start_result(sqa_dir, a)
    with with_locked_result(first) as (_, findings):
        f = Finding(message="m", file="x.py")
        add_finding(findings, f)
        apply_triage(f, "ignore", "skipped")  # ignore implies resolved
    second = start_result(sqa_dir, b)
    assert second.exists()
    assert active_result_path(sqa_dir) == second


def test_start_result_allowed_when_prior_is_empty(sqa_dir: Path):
    """An empty prior session (zero findings) doesn't block a new start."""
    a, b = _stamps_seconds_apart(2)
    start_result(sqa_dir, a)
    second = start_result(sqa_dir, b)
    assert second.exists()


def test_start_result_force_bypasses_safety_guard(sqa_dir: Path):
    """--force lets the legitimate "abandoned last session, want fresh"
    case through."""
    a, b = _stamps_seconds_apart(2)
    first = start_result(sqa_dir, a)
    with with_locked_result(first) as (_, findings):
        add_finding(findings, Finding(message="leftover", file="x.py"))
    second = start_result(sqa_dir, b, force=True)
    assert second.exists()
    assert active_result_path(sqa_dir) == second


def test_make_result_path_format(sqa_dir: Path):
    p = make_result_path(sqa_dir, datetime(2026, 5, 24, 14, 23, 18))
    assert p.name == "result_2026_05_24_142318.json"


def test_list_ignores_non_result_files(sqa_dir: Path):
    start_result(sqa_dir, datetime(2026, 5, 24, 12, 0, 0))
    (sqa_dir / "config.toml").write_text("# noise\n")
    (sqa_dir / "results.json").write_text("[]")  # close but doesn't match prefix
    (sqa_dir / "result_notatime.txt").write_text("noise")  # wrong suffix
    paths = list_result_paths(sqa_dir)
    assert len(paths) == 1
    assert paths[0].name.startswith("result_")


# --- Recording findings ----------------------------------------------------


def _record(path: Path, **kwargs) -> int:
    """Record a finding under lock, returning its allocated id."""
    with with_locked_result(path) as (_, findings):
        return add_finding(findings, Finding(**kwargs))


def test_record_finding_allocates_sequential_ids(sqa_dir: Path):
    path = start_result(sqa_dir)
    a = _record(path, message="first", file="a.py", category="logic")
    b = _record(path, message="second", file="b.py", category="logic")
    c = _record(path, message="third", file="c.py", category="logic")
    assert (a, b, c) == (1, 2, 3)


def test_findings_persisted_in_order(sqa_dir: Path):
    path = start_result(sqa_dir)
    _record(path, message="one", file="a.py")
    _record(path, message="two", file="b.py")
    findings = load_result(path)
    assert [f.id for f in findings] == [1, 2]
    assert [f.message for f in findings] == ["one", "two"]


def test_next_id_starts_at_one():
    assert next_id([]) == 1
    assert next_id([Finding(message="x", id=1)]) == 2
    # Tolerates non-contiguous IDs (defensive — shouldn't happen in practice).
    assert next_id([Finding(message="x", id=5)]) == 6


def test_record_finding_round_trips_all_fields(sqa_dir: Path):
    path = start_result(sqa_dir)
    with with_locked_result(path) as (_, findings):
        add_finding(
            findings,
            Finding(
                message="msg",
                file="src/x.py",
                line=42,
                quoted_text="raise Exception()",
                category="error-handling",
                severity="warning",
                rationale="initial",
                related=["src/y.py"],
            ),
        )
    f = load_result(path)[0]
    assert f.file == "src/x.py"
    assert f.line == 42
    assert f.quoted_text == "raise Exception()"
    assert f.category == "error-handling"
    assert f.severity == "warning"
    assert f.related == ["src/y.py"]
    assert f.triage is None
    assert f.status == "open"


# --- State machine: triage transitions ------------------------------------


def test_triage_auto_keeps_open():
    f = Finding(message="m", id=1)
    apply_triage(f, "auto", "fix it")
    assert f.triage == "auto"
    assert f.status == "open"
    assert f.rationale == "fix it"


def test_triage_ignore_implies_resolved():
    f = Finding(message="m", id=1)
    apply_triage(f, "ignore", "not applicable")
    assert f.triage == "ignore"
    assert f.status == "resolved"


def test_un_ignoring_flips_back_to_open():
    f = Finding(message="m", id=1)
    apply_triage(f, "ignore", "skip")
    assert (f.triage, f.status) == ("ignore", "resolved")
    apply_triage(f, "auto", "actually, do it")
    assert (f.triage, f.status) == ("auto", "open")


def test_no_reopen_of_action_resolved():
    f = Finding(message="m", id=1, triage="auto", status="open")
    apply_resolve(f, "fixed")
    assert f.status == "resolved"
    with pytest.raises(StateTransitionError, match="already resolved"):
        apply_triage(f, "interactive", "reconsider")


def test_no_reopen_of_interactive_resolved():
    f = Finding(message="m", id=1, triage="interactive", status="open")
    apply_resolve(f, "discussed and fixed")
    with pytest.raises(StateTransitionError, match="already resolved"):
        apply_triage(f, "auto", "...")


def test_triage_invalid_value():
    f = Finding(message="m", id=1)
    with pytest.raises(ValueError, match="invalid triage"):
        apply_triage(f, "bogus", "x")  # type: ignore[arg-type]


# --- State machine: resolve transitions -----------------------------------


def test_resolve_requires_triage():
    f = Finding(message="m", id=1)
    with pytest.raises(StateTransitionError, match="triage first"):
        apply_resolve(f, "nope")


def test_resolve_already_resolved_rejects():
    f = Finding(message="m", id=1, triage="auto", status="open")
    apply_resolve(f, "first")
    with pytest.raises(StateTransitionError, match="already resolved"):
        apply_resolve(f, "second")


def test_resolve_ignored_finding_rejects():
    """An ignore-triaged finding is already resolved; resolving again is illegal."""
    f = Finding(message="m", id=1)
    apply_triage(f, "ignore", "skip")
    with pytest.raises(StateTransitionError, match="already resolved"):
        apply_resolve(f, "redundant")


# --- has_any_resolved (safety guard helper) -------------------------------


def test_has_any_resolved_empty():
    assert has_any_resolved([]) is False


def test_has_any_resolved_all_open():
    fs = [Finding(message="m", id=1), Finding(message="m", id=2, triage="auto")]
    assert has_any_resolved(fs) is False


def test_has_any_resolved_one_ignored():
    fs = [Finding(message="m", id=1, triage="ignore", status="resolved")]
    assert has_any_resolved(fs) is True


# --- findings_for_file (file OR related match) ----------------------------


def test_findings_for_file_matches_file():
    fs = [
        Finding(message="a", id=1, file="src/x.py"),
        Finding(message="b", id=2, file="src/y.py"),
    ]
    assert [f.id for f in findings_for_file(fs, "src/x.py")] == [1]


def test_findings_for_file_matches_related():
    fs = [
        Finding(message="dry-violation", id=1, file="src/x.py", related=["src/y.py"]),
        Finding(message="other", id=2, file="src/z.py"),
    ]
    assert [f.id for f in findings_for_file(fs, "src/y.py")] == [1]


def test_findings_for_file_matches_both():
    fs = [
        Finding(message="a", id=1, file="src/x.py", related=["src/y.py"]),
        Finding(message="b", id=2, file="src/y.py"),
    ]
    # x.py matches via file on #1; y.py matches via both (#1 via related, #2 via file)
    assert [f.id for f in findings_for_file(fs, "src/y.py")] == [1, 2]


# --- Loader validation -----------------------------------------------------


def test_loader_rejects_missing_findings_key(tmp_path: Path):
    path = tmp_path / "result_2026_01_01_000000.json"
    path.write_text(json.dumps({"version": 2}))
    with pytest.raises(RuntimeError, match="missing 'findings' key"):
        load_result(path)


def test_loader_rejects_corrupt_json(tmp_path: Path):
    path = tmp_path / "result_2026_01_01_000000.json"
    path.write_text("{not json")
    with pytest.raises(RuntimeError, match="corrupt result file"):
        load_result(path)


def test_loader_rejects_illegal_state(tmp_path: Path):
    """ignore+open is rejected at load time, even if a file on disk has it."""
    path = tmp_path / "result_2026_01_01_000000.json"
    bad = {
        "version": 2,
        "timestamp": "x",
        "total": 1,
        "findings": [{"id": 1, "message": "m", "triage": "ignore", "status": "open"}],
    }
    path.write_text(json.dumps(bad))
    with pytest.raises(RuntimeError, match="ignore"):
        load_result(path)


def test_loader_rejects_resolved_untriaged(tmp_path: Path):
    path = tmp_path / "result_2026_01_01_000000.json"
    bad = {
        "version": 2,
        "timestamp": "x",
        "total": 1,
        "findings": [{"id": 1, "message": "m", "status": "resolved"}],
    }
    path.write_text(json.dumps(bad))
    with pytest.raises(RuntimeError, match="untriaged"):
        load_result(path)


# --- Concurrent write safety (smoke test of the fcntl lock) ---------------


def test_concurrent_readers_never_see_partial_writes(sqa_dir: Path):
    """A reader running concurrently with writers should never observe a
    truncated/partial JSON file. Without the shared-lock guard in
    `load_result`, a reader hitting between a writer's ``ftruncate`` and
    its ``os.write`` would see empty bytes and trip the JSON parser.

    The test hammers the file with parallel writers and a parallel reader;
    every `load_result` call must succeed.
    """
    path = start_result(sqa_dir)
    n_writers = 4
    writes_per_writer = 25
    n_reader_iterations = 200
    errors: list[BaseException] = []
    stop = threading.Event()

    def writer(label: str) -> None:
        try:
            for i in range(writes_per_writer):
                _record(path, message=f"{label}-{i}", file=f"{label}.py")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    def reader() -> None:
        try:
            for _ in range(n_reader_iterations):
                if stop.is_set():
                    return
                # Must not raise on partial writes.
                load_result(path)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    writers = [threading.Thread(target=writer, args=(f"w{i}",)) for i in range(n_writers)]
    readers = [threading.Thread(target=reader) for _ in range(2)]
    for t in writers + readers:
        t.start()
    for t in writers:
        t.join()
    stop.set()
    for t in readers:
        t.join()

    assert errors == [], f"concurrent-read errors: {errors!r}"
    # Final consistency check: all writes landed.
    assert len(load_result(path)) == n_writers * writes_per_writer


def test_concurrent_record_finding_no_id_collisions(sqa_dir: Path):
    """Hammer the result file from N threads; every finding must get a
    distinct sequential ID and all records survive."""
    path = start_result(sqa_dir)
    n_threads = 8
    per_thread = 10
    errors: list[BaseException] = []

    def worker(label: str) -> None:
        try:
            for i in range(per_thread):
                _record(path, message=f"{label}-{i}", file=f"{label}.py")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"worker errors: {errors!r}"
    findings = load_result(path)
    ids = [f.id for f in findings]
    assert len(ids) == n_threads * per_thread
    assert sorted(ids) == list(range(1, n_threads * per_thread + 1))


# --- resolve_from_argument and select_result -------------------------------


def test_resolve_from_argument_bare_filename(sqa_dir: Path):
    p = resolve_from_argument(sqa_dir, "result_2026_05_24_142318.json")
    assert p == sqa_dir / "result_2026_05_24_142318.json"


def test_resolve_from_argument_with_separator(sqa_dir: Path, tmp_path: Path):
    p = resolve_from_argument(sqa_dir, "subdir/result.json")
    # Relative-with-slash is preserved as-is (interpreted against cwd by Path).
    assert str(p) == "subdir/result.json"


def test_resolve_from_argument_absolute(sqa_dir: Path):
    p = resolve_from_argument(sqa_dir, "/abs/result.json")
    assert str(p) == "/abs/result.json"


def test_select_result_no_active_raises(sqa_dir: Path):
    with pytest.raises(FileNotFoundError, match="no active result"):
        select_result(sqa_dir, from_value=None)


def test_select_result_returns_active(sqa_dir: Path):
    path = start_result(sqa_dir)
    assert select_result(sqa_dir, from_value=None) == path


def test_select_result_with_from(sqa_dir: Path):
    a, b = _stamps_seconds_apart(2)
    pa = start_result(sqa_dir, a)
    start_result(sqa_dir, b)  # this is "active"
    selected = select_result(sqa_dir, from_value=pa.name)
    assert selected == pa


def test_select_result_with_missing_from_raises(sqa_dir: Path):
    start_result(sqa_dir)
    with pytest.raises(FileNotFoundError, match="does not exist"):
        select_result(sqa_dir, from_value="result_2099_01_01_000000.json")


def test_is_active(sqa_dir: Path):
    a, b = _stamps_seconds_apart(2)
    pa = start_result(sqa_dir, a)
    pb = start_result(sqa_dir, b)
    assert is_active(sqa_dir, pb) is True
    assert is_active(sqa_dir, pa) is False


# --- Round-trip find_by_id under lock --------------------------------------


def test_locked_modify_persists(sqa_dir: Path):
    path = start_result(sqa_dir)
    _record(path, message="m", file="x.py")
    with with_locked_result(path) as (_, findings):
        f = find_by_id(findings, 1)
        apply_triage(f, "auto", "fix it")
    again = load_result(path)
    assert again[0].triage == "auto"
    assert again[0].rationale == "fix it"


def test_find_by_id_raises_on_missing():
    with pytest.raises(KeyError):
        find_by_id([Finding(message="m", id=1)], 99)


def test_format_version_constant():
    """Pinned: if we bump the version, every test that asserts version=2
    needs to be revisited."""
    assert result_file._RESULT_FORMAT_VERSION == 2
