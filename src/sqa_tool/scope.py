"""Scope resolution: anchor-location → scope, ancestor walk for findings-for-file."""

import fnmatch
from pathlib import Path

from sqa_tool import anchors, findings, paths


def _ancestor_dirs(rel_path: Path) -> list[Path]:
    """Return ancestor directories (relative to project root), root-first.

    e.g. Path('auth/sub/login.py') → [Path('.'), Path('auth'), Path('auth/sub')]
    """
    parts = rel_path.parent.parts
    out = [Path(".")]
    accum = Path(".")
    for p in parts:
        accum = accum / p
        out.append(accum)
    return out


def _scope_files_for(project_root: Path, rel_file: str) -> list[Path]:
    """Yield candidate `.sqa.md` paths to search for higher-scope findings."""
    rel = Path(rel_file)
    out = []
    for ancestor in _ancestor_dirs(rel):
        candidate = project_root / ancestor / paths.SCOPE_FILE_NAME
        if candidate.exists():
            out.append(candidate)
    return out


def _matches_related(rel_file: str, related: list[str]) -> bool:
    """True if `rel_file` matches any path in `related` (literal or fnmatch)."""
    for pat in related:
        if pat == rel_file:
            return True
        if fnmatch.fnmatch(rel_file, pat):
            return True
    return False


def findings_for_file(project_root: Path, rel_file: str) -> list[tuple[str, findings.Finding]]:
    """Return (id, Finding) pairs in scope for `rel_file`.

    Includes:
      - Findings whose anchor is directly in `rel_file`.
      - Findings whose anchor is in an ancestor `.sqa.md` AND whose related_files
        matches `rel_file`.
    """
    out: list[tuple[str, findings.Finding]] = []
    seen: set[str] = set()

    file_path = project_root / rel_file
    if file_path.exists():
        for fid in anchors.find_anchors_in_file(file_path):
            if fid in seen:
                continue
            seen.add(fid)
            try:
                out.append((fid, findings.load_finding(project_root, fid)))
            except FileNotFoundError:
                # Orphan anchor — skip; surfaced separately by the orphans command.
                continue

    for scope_file in _scope_files_for(project_root, rel_file):
        for fid in anchors.find_anchors_in_file(scope_file):
            if fid in seen:
                continue
            try:
                f = findings.load_finding(project_root, fid)
            except FileNotFoundError:
                continue
            if _matches_related(rel_file, f.related_files):
                seen.add(fid)
                out.append((fid, f))

    return out
