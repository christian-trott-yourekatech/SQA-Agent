"""Per-run result-file storage for v2.1.

One result file per review session, at ``.sqa/result_<YYYY_MM_DD_HHMMSS>.json``.
The "active" result file is the most recent one (by lexical filename order,
which matches creation order given the timestamp suffix).

All mutations of a result file go through :func:`with_locked_result`, which
holds an ``fcntl`` exclusive lock over the read-modify-write cycle. This
matches the pattern in ``file_status.py`` and serializes concurrent writers
(parallel ``review-file`` / ``triage-file`` subagents).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

from sqa_tool import _locked_file

# --- Schema constants -------------------------------------------------------

_RESULT_PREFIX = "result_"
_RESULT_SUFFIX = ".json"
_RESULT_FORMAT_VERSION = 2
_TIMESTAMP_FMT = "%Y_%m_%d_%H%M%S"

Severity = Literal["info", "warning", "error"]
Triage = Literal["auto", "interactive", "ignore"]
Status = Literal["open", "resolved"]

_VALID_SEVERITIES = set(get_args(Severity))
_VALID_TRIAGES = set(get_args(Triage))
_VALID_STATUSES = set(get_args(Status))


# --- Data model -------------------------------------------------------------


@dataclass
class Finding:
    """A single finding in a result file.

    ``id`` is allocated by :func:`record_finding` and is unique within the
    containing result file (not across files). Most fields are optional with
    sensible defaults; ``message`` is the only required field at construction
    time.
    """

    message: str
    id: int = 0
    file: str | None = None
    line: int | None = None
    quoted_text: str | None = None
    category: str = ""
    severity: Severity = "info"
    triage: Triage | None = None
    rationale: str = ""
    status: Status = "open"
    related: list[str] = field(default_factory=list)


# --- Validation -------------------------------------------------------------


def _validate(finding: Finding) -> None:
    if finding.severity not in _VALID_SEVERITIES:
        raise ValueError(f"Invalid severity: {finding.severity!r}")
    if finding.triage is not None and finding.triage not in _VALID_TRIAGES:
        raise ValueError(f"Invalid triage: {finding.triage!r}")
    if finding.status not in _VALID_STATUSES:
        raise ValueError(f"Invalid status: {finding.status!r}")
    # State-machine invariants. Two combinations are illegal regardless of how
    # we got there; reject them at the storage boundary so a corrupted file
    # can't silently propagate.
    if finding.triage is None and finding.status == "resolved":
        raise ValueError("invalid state: untriaged finding cannot be resolved")
    if finding.triage == "ignore" and finding.status == "open":
        raise ValueError("invalid state: triage=ignore implies status=resolved")


def _finding_from_dict(data: dict[str, Any]) -> Finding:
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object, got {type(data).__name__}")
    if "message" not in data:
        raise ValueError("missing required field: message")
    known = {f.name for f in fields(Finding)}
    payload = {k: v for k, v in data.items() if k in known}
    if "related" in payload:
        rel = payload["related"]
        if not isinstance(rel, list) or not all(isinstance(p, str) for p in rel):
            raise ValueError("'related' must be a list of strings")
    finding = Finding(**payload)
    _validate(finding)
    return finding


# --- Path helpers -----------------------------------------------------------


def make_result_path(sqa_dir: Path, now: datetime | None = None) -> Path:
    """Build a fresh timestamped result-file path. Does not create the file."""
    stamp = (now or datetime.now()).strftime(_TIMESTAMP_FMT)
    return sqa_dir / f"{_RESULT_PREFIX}{stamp}{_RESULT_SUFFIX}"


def _is_result_filename(name: str) -> bool:
    return name.startswith(_RESULT_PREFIX) and name.endswith(_RESULT_SUFFIX)


def list_result_paths(sqa_dir: Path) -> list[Path]:
    """All result files in `.sqa/`, sorted oldest → newest by filename."""
    if not sqa_dir.exists():
        return []
    out = [p for p in sqa_dir.iterdir() if p.is_file() and _is_result_filename(p.name)]
    out.sort()
    return out


def active_result_path(sqa_dir: Path) -> Path | None:
    """The most recent result file, or ``None`` if none exists."""
    paths_ = list_result_paths(sqa_dir)
    return paths_[-1] if paths_ else None


def active_result_or_exit_message(sqa_dir: Path) -> Path | None:
    """Return the active result path, or print the canonical "no active
    result" error to stderr and return ``None``.

    Lives next to :func:`active_result_path` so the error wording stays in
    one place. Callers translate the ``None`` return into their own
    handler's exit-code shape (e.g. ``return 1`` for a CLI command,
    ``return None`` for a helper that signals failure to its caller).
    """
    path = active_result_path(sqa_dir)
    if path is None:
        print(
            "error: no active result file. Run `sqa-tool start-result` first.",
            file=sys.stderr,
        )
    return path


def resolve_from_argument(sqa_dir: Path, value: str) -> Path:
    """Resolve a ``--from`` value to a Path.

    - Absolute paths and paths containing a separator are used as-is
      (relative paths are interpreted against cwd, matching shell expectation).
    - A bare filename (no separator) is resolved against ``sqa_dir``.

    The returned path is not required to exist; callers decide whether absence
    is an error in context.
    """
    if os.sep in value or (os.altsep and os.altsep in value):
        return Path(value)
    return sqa_dir / value


# --- Parse / serialize -----------------------------------------------------
#
# Byte-level lock/read/write is in `sqa_tool._locked_file`; this module owns
# the result-file schema (parse to header + Finding list; serialize back).


def _parse(raw: str, path: Path) -> tuple[dict[str, Any], list[Finding]]:
    """Parse a result-file payload; returns (header_metadata, findings)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"corrupt result file at {path}: {e}") from e
    if not isinstance(data, dict) or "findings" not in data:
        raise RuntimeError(f"corrupt result file at {path}: missing 'findings' key")
    if not isinstance(data["findings"], list):
        raise RuntimeError(f"corrupt result file at {path}: 'findings' must be a list")
    findings = []
    for i, entry in enumerate(data["findings"]):
        try:
            findings.append(_finding_from_dict(entry))
        except ValueError as e:
            raise RuntimeError(f"corrupt result file at {path}: findings[{i}]: {e}") from e
    header = {k: v for k, v in data.items() if k != "findings"}
    return header, findings


def _serialize(header: dict[str, Any], findings: list[Finding]) -> str:
    payload = {
        "version": header.get("version", _RESULT_FORMAT_VERSION),
        "timestamp": header.get("timestamp", ""),
        "total": len(findings),
        "findings": [asdict(f) for f in findings],
    }
    return json.dumps(payload, indent=2) + "\n"


# --- Public API: create, load, mutate --------------------------------------


class UnresolvedFindingsError(RuntimeError):
    """Raised by :func:`start_result` (without ``force``) when the previous
    session's result file still has open findings."""


def start_result(sqa_dir: Path, now: datetime | None = None, force: bool = False) -> Path:
    """Create a fresh result file in ``sqa_dir`` and return its path.

    The file is initialized with an empty findings list and a header carrying
    the format version and timestamp.

    **Safety guard.** If the most recent existing result file has any open
    (status=open) findings, ``start_result`` raises
    :class:`UnresolvedFindingsError` instead of creating a new file. This
    catches the most common failure mode: a wayward subagent inside an
    in-progress session calling ``start-result`` and rotating the "active"
    pointer out from under everybody. The legitimate "I aborted last time
    but want a new session anyway" case is unblocked by passing
    ``force=True``.

    Raises :class:`FileExistsError` if a file at the chosen timestamped
    path already exists (two calls within the same second — very rare;
    surface rather than silently overwrite).
    """
    sqa_dir.mkdir(parents=True, exist_ok=True)

    if not force:
        active = active_result_path(sqa_dir)
        if active is not None:
            open_count = sum(1 for f in load_result(active) if f.status == "open")
            if open_count > 0:
                raise UnresolvedFindingsError(
                    f"previous session {active.name} has {open_count} unresolved "
                    "finding(s). Resolve or ignore them first, or pass force=True "
                    "to start a new session anyway."
                )

    now = now or datetime.now()
    path = make_result_path(sqa_dir, now)
    if path.exists():
        raise FileExistsError(f"result file already exists: {path}")
    header = {"version": _RESULT_FORMAT_VERSION, "timestamp": now.strftime(_TIMESTAMP_FMT)}
    path.write_text(_serialize(header, []))
    return path


def load_result(path: Path) -> list[Finding]:
    """Read a result file and return its findings list.

    Acquires a shared (``LOCK_SH``) lock for the duration of the read so a
    concurrent writer mid-``write_all`` — between its ``ftruncate`` and
    its ``os.write`` — can't expose a truncated file to this reader.
    Multiple readers may hold ``LOCK_SH`` concurrently; only writers block.
    """
    with _locked_file.locked(path, fcntl.LOCK_SH) as fd:
        _, findings = _parse(_locked_file.read_all(fd), path)
    return findings


def load_result_header(path: Path) -> dict[str, Any]:
    """Return the result file's header metadata (version, timestamp, total).

    Same locking rationale as :func:`load_result`.
    """
    with _locked_file.locked(path, fcntl.LOCK_SH) as fd:
        header, _ = _parse(_locked_file.read_all(fd), path)
    return header


@contextlib.contextmanager
def with_locked_result(path: Path) -> Iterator[tuple[dict[str, Any], list[Finding]]]:
    """Open `path` under exclusive lock; yield (header, findings).

    Mutations to ``findings`` (in place) are persisted on context exit. The
    header is preserved as-is across the write.
    """
    with _locked_file.locked(path) as fd:
        header, findings = _parse(_locked_file.read_all(fd), path)
        yield header, findings
        _locked_file.write_all(fd, _serialize(header, findings))


# --- Higher-level operations -----------------------------------------------


def has_any_resolved(findings: list[Finding]) -> bool:
    """True if any finding has ``status == 'resolved'``. Used by the
    record-finding safety guard."""
    return any(f.status == "resolved" for f in findings)


def find_by_id(findings: list[Finding], finding_id: int) -> Finding:
    for f in findings:
        if f.id == finding_id:
            return f
    raise KeyError(f"no finding with id {finding_id}")


def next_id(findings: list[Finding]) -> int:
    """Allocate the next sequential ID. IDs start at 1."""
    return (max((f.id for f in findings), default=0)) + 1


def add_finding(findings: list[Finding], finding: Finding) -> int:
    """Append a new finding with a freshly allocated ID. Returns the ID.

    Caller is responsible for the result-file lock (use ``with_locked_result``)
    and for the safety-guard check (``has_any_resolved``) when relevant.
    """
    _validate(finding)
    finding.id = next_id(findings)
    findings.append(finding)
    return finding.id


# State machine: apply_triage / apply_resolve. See Docs/v2.1-design.md § 3.2
# for the full transition table.


class StateTransitionError(ValueError):
    """Raised when a requested state transition is illegal (e.g. reopening
    an action-resolved finding)."""


def apply_triage(finding: Finding, triage: Triage, rationale: str) -> None:
    """Apply a triage transition in place. Enforces the § 3.2 state machine.

    - ``ignore`` always implies ``status=resolved`` (same call).
    - Re-triaging an ``ignore + resolved`` finding to ``auto`` / ``interactive``
      flips status back to ``open`` (un-ignoring).
    - Re-triaging an action-resolved finding (auto/interactive + resolved) is
      rejected — no reopen.
    """
    if triage not in _VALID_TRIAGES:
        raise ValueError(f"invalid triage value: {triage!r}")

    # Reject reopen of action-resolved findings.
    if finding.status == "resolved" and finding.triage in ("auto", "interactive"):
        raise StateTransitionError(
            f"cannot re-triage finding {finding.id}: already resolved via "
            f"{finding.triage}. To re-surface, record a fresh finding."
        )

    finding.triage = triage
    finding.rationale = rationale
    if triage == "ignore":
        finding.status = "resolved"
    else:
        # auto / interactive: ensure status is open (handles un-ignoring).
        finding.status = "open"
    _validate(finding)


def apply_resolve(finding: Finding, rationale: str) -> None:
    """Resolve a finding (transition status to ``resolved``).

    - The finding must be triaged (untriaged → resolve is rejected).
    - Already-resolved findings are rejected (idempotency would mask bugs;
      callers should check status first).
    """
    if finding.triage is None:
        raise StateTransitionError(f"cannot resolve untriaged finding {finding.id}: triage first.")
    if finding.status == "resolved":
        raise StateTransitionError(f"finding {finding.id} is already resolved.")
    finding.status = "resolved"
    finding.rationale = rationale
    _validate(finding)


# --- Read helpers (no lock; readers tolerate stale views) ------------------


def findings_for_file(findings: list[Finding], rel_path: str) -> list[Finding]:
    """Findings whose ``file`` matches ``rel_path`` OR whose ``related`` list
    contains it. Returns in ``id`` order (the same order they appear in the
    result file)."""
    return [f for f in findings if f.file == rel_path or rel_path in f.related]


# --- Resolution of the active result, with optional --from override --------


def select_result(sqa_dir: Path, from_value: str | None) -> Path:
    """Resolve the result file a command should operate on.

    - If ``from_value`` is None, returns the active (most recent) result.
    - Otherwise resolves the value via :func:`resolve_from_argument`.

    Raises ``FileNotFoundError`` if no result file exists or the resolved
    path doesn't exist.
    """
    if from_value is None:
        path = active_result_path(sqa_dir)
        if path is None:
            raise FileNotFoundError(
                f"no active result file in {sqa_dir}. Run `sqa-tool start-result` first."
            )
        return path
    path = resolve_from_argument(sqa_dir, from_value)
    if not path.exists():
        raise FileNotFoundError(f"result file does not exist: {path}")
    return path


def is_active(sqa_dir: Path, path: Path) -> bool:
    """True if ``path`` is the active (most recent) result file."""
    active = active_result_path(sqa_dir)
    return active is not None and active.resolve() == path.resolve()
