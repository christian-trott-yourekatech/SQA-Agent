"""Thin wrappers over git commands used by sqa-tool."""

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Raised when a git invocation fails or the directory isn't a git repo."""


def _git(project_root: Path, *args: str, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            input=input_text,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise GitError("git executable not found in PATH") from e
    except subprocess.CalledProcessError as e:
        raise GitError(
            f"git {' '.join(args)} failed (exit {e.returncode}): {e.stderr.strip()}"
        ) from e
    return result.stdout


def is_repo(project_root: Path) -> bool:
    """True iff project_root is inside a git working tree."""
    try:
        out = _git(project_root, "rev-parse", "--is-inside-work-tree")
    except GitError:
        return False
    return out.strip() == "true"


def ls_files(project_root: Path) -> list[str]:
    """Return project-relative paths of all git-tracked files in the project root."""
    out = _git(project_root, "ls-files")
    return [line for line in out.splitlines() if line]


def hash_object(project_root: Path, rel_paths: list[str]) -> dict[str, str]:
    """Compute git blob hashes for a list of project-relative paths.

    Uses a single `git hash-object --stdin-paths` invocation. Missing files are
    omitted from the result.
    """
    if not rel_paths:
        return {}
    existing = [p for p in rel_paths if (project_root / p).exists()]
    if not existing:
        return {}
    stdin = "\n".join(str(project_root / p) for p in existing)
    out = _git(project_root, "hash-object", "--stdin-paths", input_text=stdin)
    hashes = out.splitlines()
    return dict(zip(existing, hashes, strict=False))


def diff_blob_to_file(project_root: Path, blob: str, rel_path: str) -> str:
    """Return a unified diff of <blob> vs the current on-disk content of <rel_path>.

    If `blob` is empty (no prior reviewed state), returns the file content marked
    as added. If the file no longer exists, returns the prior blob's content
    marked as removed.
    """
    file_path = project_root / rel_path
    file_exists = file_path.exists()
    if not blob and not file_exists:
        return ""
    if not blob:
        with open(file_path) as f:
            content = f.read()
        return _format_synthetic_diff(rel_path, "", content)
    if not file_exists:
        old = _git(project_root, "show", blob)
        return _format_synthetic_diff(rel_path, old, "")
    current = _git(project_root, "hash-object", "-w", "--", str(file_path)).strip()
    if current == blob:
        return ""
    return _git(project_root, "diff", blob, current, "--", rel_path)


def _format_synthetic_diff(rel_path: str, old: str, new: str) -> str:
    """Minimal unified-diff synthesis for the no-prior or deleted-file cases."""
    head = f"--- a/{rel_path}\n+++ b/{rel_path}\n"
    if not old:
        body = "".join(f"+{line}\n" for line in new.splitlines())
    elif not new:
        body = "".join(f"-{line}\n" for line in old.splitlines())
    else:
        body = ""
    return head + body
