"""Finding data model + JSON I/O + ID allocation."""

import json
import re
import secrets
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Literal, get_args

from sqa_tool import paths

Severity = Literal["info", "warning", "error"]
Triage = Literal["auto", "interactive", "ignore"]

_VALID_SEVERITIES = set(get_args(Severity))
_VALID_TRIAGES = set(get_args(Triage))

# RFC4648 base32 alphabet — A-Z2-7, no ambiguous chars.
ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
ID_LENGTH = 5
ID_RE = re.compile(rf"^[{re.escape(ID_ALPHABET)}]{{{ID_LENGTH}}}$")


@dataclass
class Finding:
    """Stored finding metadata. ID is the filename, not a field."""

    message: str
    severity: Severity = "info"
    triage: Triage | None = None
    rationale: str = ""
    related_files: list[str] = field(default_factory=list)


def is_valid_id(s: str) -> bool:
    return bool(ID_RE.match(s))


def gen_id() -> str:
    """Generate a fresh random base32 ID."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def alloc_id(project_root: Path, max_attempts: int = 100) -> str:
    """Allocate a fresh ID that doesn't collide with an existing finding file."""
    fdir = paths.findings_dir(project_root)
    for _ in range(max_attempts):
        candidate = gen_id()
        if not (fdir / f"{candidate}.json").exists():
            return candidate
    raise RuntimeError(f"Could not allocate a free ID after {max_attempts} attempts")


def _validate(finding: Finding) -> None:
    """Raise ValueError if any Literal-typed field holds an out-of-contract value."""
    if finding.severity not in _VALID_SEVERITIES:
        raise ValueError(f"Invalid severity: {finding.severity!r}")
    if finding.triage is not None and finding.triage not in _VALID_TRIAGES:
        raise ValueError(f"Invalid triage: {finding.triage!r}")


def save_finding(project_root: Path, finding_id: str, finding: Finding) -> None:
    """Write the finding to .sqa/findings/<id>.json."""
    if not is_valid_id(finding_id):
        raise ValueError(f"Invalid finding ID: {finding_id!r}")
    _validate(finding)
    path = paths.finding_path(project_root, finding_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(finding), indent=2) + "\n")


def load_finding(project_root: Path, finding_id: str) -> Finding:
    if not is_valid_id(finding_id):
        raise ValueError(f"Invalid finding ID: {finding_id!r}")
    path = paths.finding_path(project_root, finding_id)
    if not path.exists():
        raise FileNotFoundError(f"No finding with ID {finding_id}")
    raw = path.read_text()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Corrupted finding {finding_id} at {path}: invalid JSON ({e})") from e
    try:
        return _finding_from_dict(data)
    except KeyError as e:
        raise ValueError(
            f"Corrupted finding {finding_id} at {path}: missing required field {e}"
        ) from e
    except ValueError as e:
        raise ValueError(f"Corrupted finding {finding_id} at {path}: {e}") from e


def _finding_from_dict(data: dict) -> Finding:
    """Construct a Finding from a JSON dict.

    Defaults for optional fields come from the Finding dataclass itself —
    any field absent from `data` is left at its dataclass default rather
    than re-stating the default here, so a default change in one place
    can't silently diverge from the loader.
    """
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object at the top level, got {type(data).__name__}")
    optional_names = {f.name for f in fields(Finding)} - {"message"}
    overrides = {k: data[k] for k in optional_names if k in data}
    if "related_files" in overrides:
        rf = overrides["related_files"]
        if not isinstance(rf, list):
            raise ValueError(f"related_files must be a list, got {type(rf).__name__}")
        overrides["related_files"] = list(rf)
    finding = Finding(message=data["message"], **overrides)
    _validate(finding)
    return finding


def list_finding_ids(project_root: Path) -> list[str]:
    """Return all valid finding IDs in the findings directory, sorted."""
    fdir = paths.findings_dir(project_root)
    if not fdir.exists():
        return []
    ids = []
    for p in fdir.iterdir():
        if p.suffix != ".json":
            continue
        stem = p.stem
        if is_valid_id(stem):
            ids.append(stem)
    ids.sort()
    return ids


def delete_finding(project_root: Path, finding_id: str) -> None:
    if not is_valid_id(finding_id):
        raise ValueError(f"Invalid finding ID: {finding_id!r}")
    path = paths.finding_path(project_root, finding_id)
    if path.exists():
        path.unlink()
