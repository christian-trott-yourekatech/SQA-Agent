"""sqa-tool orphans — detect and (where deterministic) auto-fix anchor/finding rot."""

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

from sqa_tool import anchors, findings, git_ops, paths


def _walk_anchorable_files(project_root: Path) -> Iterator[tuple[str, Path]]:
    """Yield (rel_path, abs_path) for every git-tracked file that may carry anchors."""
    for rel in git_ops.ls_files(project_root):
        abs_path = project_root / rel
        if not abs_path.is_file():
            continue
        yield rel, abs_path


def _collect_anchored_ids(project_root: Path) -> dict[str, list[str]]:
    """Build a map: finding_id → list of rel_paths in which it's anchored."""
    out: dict[str, list[str]] = {}
    for rel, abs_path in _walk_anchorable_files(project_root):
        try:
            ids = anchors.find_anchors_in_file(abs_path)
        except (UnicodeDecodeError, OSError):
            continue
        for fid in ids:
            out.setdefault(fid, []).append(rel)
    return out


def _is_scope_md(rel: str) -> bool:
    return Path(rel).name == paths.SCOPE_FILE_NAME


def _delete_empty_scope_md_files(project_root: Path) -> list[str]:
    """Auto-fix: delete .sqa.md files that contain no anchors. Returns deleted rel-paths."""
    deleted = []
    for rel, abs_path in _walk_anchorable_files(project_root):
        if not _is_scope_md(rel):
            continue
        try:
            ids = anchors.find_anchors_in_file(abs_path)
        except (UnicodeDecodeError, OSError):
            continue
        if not ids:
            abs_path.unlink()
            deleted.append(rel)
    return deleted


def _add_missing_related_for_source_anchors(
    project_root: Path, anchored: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """Auto-fix: for each finding whose anchor is in a source file (not .sqa.md),
    if the file isn't in related_files, add it. Returns (finding_id, rel_path) pairs added.
    """
    added: list[tuple[str, str]] = []
    for fid, rels in anchored.items():
        try:
            f = findings.load_finding(project_root, fid)
        except (FileNotFoundError, ValueError):
            continue
        modified = False
        for rel in rels:
            if _is_scope_md(rel):
                continue
            if rel not in f.related_files:
                f.related_files.append(rel)
                modified = True
                added.append((fid, rel))
        if modified:
            findings.save_finding(project_root, fid, f)
    return added


def _report(project_root: Path, anchored: dict[str, list[str]]) -> dict[str, list]:
    """Compute the non-auto-fixable orphan classes."""
    json_ids = set(findings.list_finding_ids(project_root))
    anchor_ids = set(anchored.keys())

    findings_without_anchors = sorted(json_ids - anchor_ids)
    anchors_without_findings: list[dict] = []
    for fid in sorted(anchor_ids - json_ids):
        anchors_without_findings.append({"id": fid, "in_files": anchored[fid]})

    stale_related: list[dict] = []
    for fid in sorted(json_ids):
        try:
            f = findings.load_finding(project_root, fid)
        except (FileNotFoundError, ValueError):
            continue
        missing = [rel for rel in f.related_files if not (project_root / rel).exists()]
        if missing:
            stale_related.append({"id": fid, "missing": missing})

    return {
        "findings_without_anchors": findings_without_anchors,
        "anchors_without_findings": anchors_without_findings,
        "stale_related_files": stale_related,
    }


def run(project_root: Path, args: argparse.Namespace) -> int:
    deleted_md = _delete_empty_scope_md_files(project_root)
    anchored = _collect_anchored_ids(project_root)
    related_added = _add_missing_related_for_source_anchors(project_root, anchored)
    report = _report(project_root, anchored)

    payload = {
        "auto_fixed": {
            "deleted_empty_scope_files": deleted_md,
            "added_related_files": [{"id": fid, "added": rel} for fid, rel in related_added],
        },
        "reported": report,
    }
    print(json.dumps(payload, indent=2))
    return 0
