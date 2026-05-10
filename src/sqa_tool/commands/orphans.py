"""sqa-tool orphans — detect and (where deterministic) auto-fix anchor/finding rot."""

import argparse
import json
from pathlib import Path

from sqa_tool import anchors, findings, git_ops, paths


def _collect_anchored_ids(project_root: Path) -> dict[str, list[str]]:
    """Build a map: finding_id → list of rel_paths in which it's anchored.

    Skips anchors that appear inside Python string literals or markdown
    fenced code blocks — those are test fixtures and documentation
    examples, not real anchors.
    """
    # OSError is suppressed here (transient unreadable file → skip and
    # try again next scan; orphan reporting is read-only and self-healing).
    # Contrast with triage._find_files_with_anchor, which intentionally lets
    # OSError propagate because resolve() is destructive and must not split
    # its action.
    out: dict[str, list[str]] = {}
    for rel, abs_path in git_ops.walk_tracked_files(project_root):
        try:
            ids = anchors.find_anchors_for_orphan_scan(abs_path)
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
    for rel, abs_path in git_ops.walk_tracked_files(project_root):
        if not _is_scope_md(rel):
            continue
        try:
            ids = anchors.find_anchors_for_orphan_scan(abs_path)
        except (UnicodeDecodeError, OSError):
            continue
        if not ids:
            git_ops.git_rm(project_root, rel)
            deleted.append(rel)
    return deleted


def _load_findings(
    project_root: Path,
) -> tuple[dict[str, "findings.Finding"], list[str]]:
    """Load every finding by ID; return (loaded, unreadable).

    `unreadable` collects IDs whose JSON failed to parse (ValueError) — these
    get reported as a distinct orphan class instead of being silently dropped.
    IDs that raise FileNotFoundError (a list/load race) are simply skipped.
    """
    loaded: dict[str, findings.Finding] = {}
    unreadable: list[str] = []
    for fid in findings.list_finding_ids(project_root):
        try:
            loaded[fid] = findings.load_finding(project_root, fid)
        except FileNotFoundError:
            continue
        except ValueError:
            unreadable.append(fid)
    return loaded, unreadable


def _add_missing_related_for_source_anchors(
    project_root: Path,
    anchored: dict[str, list[str]],
    loaded: dict[str, "findings.Finding"],
) -> list[tuple[str, str]]:
    """Auto-fix: for each finding whose anchor is in a source file (not .sqa.md),
    if the file isn't in related_files, add it. Returns (finding_id, rel_path) pairs added.
    """
    added: list[tuple[str, str]] = []
    for fid, rels in anchored.items():
        f = loaded.get(fid)
        if f is None:
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


def _report(
    project_root: Path,
    anchored: dict[str, list[str]],
    loaded: dict[str, "findings.Finding"],
    unreadable: list[str],
) -> dict[str, list]:
    """Compute the non-auto-fixable orphan classes.

    Findings whose JSON failed to parse are surfaced as a distinct
    `unreadable_findings` class — exactly the rot the orphans command exists
    to flag — rather than silently disappearing from the report.
    """
    open_ids = {fid for fid, f in loaded.items() if f.status != "resolved"}
    anchor_ids = set(anchored.keys())
    json_ids = set(loaded) | set(unreadable)

    findings_without_anchors = sorted(open_ids - anchor_ids)
    anchors_without_findings = [
        {"id": fid, "in_files": anchored[fid]} for fid in sorted(anchor_ids - json_ids)
    ]
    stale_related: list[dict] = []
    for fid in sorted(loaded):
        f = loaded[fid]
        missing = [rel for rel in f.related_files if not (project_root / rel).exists()]
        if missing:
            stale_related.append({"id": fid, "missing": missing})

    return {
        "findings_without_anchors": findings_without_anchors,
        "anchors_without_findings": anchors_without_findings,
        "stale_related_files": stale_related,
        "unreadable_findings": sorted(unreadable),
    }


def run(project_root: Path, args: argparse.Namespace) -> int:
    deleted_md = _delete_empty_scope_md_files(project_root)
    anchored = _collect_anchored_ids(project_root)
    loaded, unreadable = _load_findings(project_root)
    related_added = _add_missing_related_for_source_anchors(project_root, anchored, loaded)
    report = _report(project_root, anchored, loaded, unreadable)

    payload = {
        "auto_fixed": {
            "deleted_empty_scope_files": deleted_md,
            "added_related_files": [{"id": fid, "added": rel} for fid, rel in related_added],
        },
        "reported": report,
    }
    print(json.dumps(payload, indent=2))
    return 0
