"""fcntl-locked read-modify-write of .sqa/file_status.json."""

import fcntl
import json
from pathlib import Path

from sqa_tool import _locked_file, paths

# Seed written into a newly-created file_status.json so the first reader
# sees a parseable empty mapping rather than zero bytes. The seed is
# applied under `LOCK_EX` by `_locked_file.locked` — see its docstring
# for the race-free-init contract.
_SEED = b"{}\n"


def load(project_root: Path) -> dict[str, str]:
    """Load the file_status mapping (rel_path → blob hash).

    Returns `{}` if the file is missing or empty. Empty-file handling
    matters because `_locked_file.locked` only seeds `{}` under
    `LOCK_EX`; a `LOCK_SH` reader observing a zero-byte file (e.g.
    between `O_CREAT` and the first writer's `write_all`) would
    otherwise feed an empty string to `_parse_status` and trip a
    JSON-decode error.
    """
    path = paths.file_status_path(project_root)
    with _locked_file.locked(path, fcntl.LOCK_SH, create_with=_SEED) as fd:
        raw = _locked_file.read_all(fd)
        if raw == "":
            return {}
        return _parse_status(raw, path)


def _parse_status(raw: str, path: Path) -> dict[str, str]:
    """Parse the locked file's contents, raising on malformed JSON or
    wrong shape.

    Three failure modes all surface as a single ``RuntimeError`` whose
    message starts with ``"Corrupt file_status at <path>: ..."``:

      - Malformed JSON (caught at ``json.loads``).
      - Valid JSON whose top level isn't a dict (e.g. ``[]``, ``"foo"``,
        ``123``). Downstream ``update``/``remove`` would otherwise crash
        with a cryptic ``TypeError`` while trying to ``__setitem__`` on
        the wrong type.
      - Valid dict whose values aren't all strings (e.g. someone
        hand-edited a hash to an int). Reads would later mis-compare
        the stored value against fresh ``git hash-object`` output and
        silently re-flag the file as changed.

    Recovery is not attempted (no "drop bad entries, keep good ones") —
    ``file_status.json`` is tool-internal state and any deviation
    indicates corruption that should surface to the user, not be
    silently massaged into a different shape.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Corrupt file_status at {path}: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(
            f"Corrupt file_status at {path}: expected JSON object at top "
            f"level, got {type(data).__name__}"
        )
    # Value check matters in practice — a hand-edited hash → int would
    # otherwise propagate quietly. (Keys are always str: json.loads of a
    # JSON object guarantees it.)
    for v in data.values():
        if not isinstance(v, str):
            raise RuntimeError(
                f"Corrupt file_status at {path}: every value must be a "
                f"string; got value={type(v).__name__}"
            )
    return data


def _serialize(status: dict[str, str]) -> str:
    """Serialize the mapping with the deterministic format the persisted
    file uses (``indent=2``, ``sort_keys=True``, trailing newline).

    Pinned here so format choices stay in one place and so the
    persistence contract is easy to inspect alongside ``_parse_status``.
    """
    return json.dumps(status, indent=2, sort_keys=True) + "\n"


def update(project_root: Path, rel_path: str, blob_hash: str) -> None:
    """Update one entry under lock (read-modify-write)."""
    path = paths.file_status_path(project_root)
    with _locked_file.locked(path, create_with=_SEED) as fd:
        status = _parse_status(_locked_file.read_all(fd), path)
        status[rel_path] = blob_hash
        _locked_file.write_all(fd, _serialize(status))


def remove(project_root: Path, rel_path: str) -> None:
    """Remove one entry under lock."""
    path = paths.file_status_path(project_root)
    with _locked_file.locked(path, create_with=_SEED) as fd:
        status = _parse_status(_locked_file.read_all(fd), path)
        status.pop(rel_path, None)
        _locked_file.write_all(fd, _serialize(status))
