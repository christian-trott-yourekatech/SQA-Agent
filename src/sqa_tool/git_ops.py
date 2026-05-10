"""Thin wrappers over git commands used by sqa-tool."""

import difflib
import subprocess
from collections.abc import Iterator
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
            encoding="utf-8",
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


def has_commits(project_root: Path) -> bool:
    """True iff HEAD resolves to a commit."""
    try:
        _git(project_root, "rev-parse", "HEAD")
    except GitError:
        return False
    return True


def ls_files(project_root: Path) -> list[str]:
    """Return project-relative paths of all git-tracked files in the project root.

    Uses NUL-delimited output (`-z`) so paths containing whitespace, embedded
    quotes, or non-UTF-8 bytes are returned verbatim rather than in git's
    C-style quoted form.
    """
    out = _git(project_root, "ls-files", "-z")
    return [p for p in out.split("\0") if p]


def git_rm(project_root: Path, rel_path: str) -> None:
    """Remove `rel_path` from the working tree and stage the deletion.

    The caller is still responsible for committing the index change; this
    just keeps the working tree and index consistent so `git status` doesn't
    show a tracked-but-missing file.
    """
    _git(project_root, "rm", "--", rel_path)


def walk_tracked_files(project_root: Path) -> Iterator[tuple[str, Path]]:
    """Yield (rel_path, abs_path) for every git-tracked file that exists on disk.

    Returns nothing if `project_root` isn't a git working tree.
    """
    if not is_repo(project_root):
        return
    for rel in ls_files(project_root):
        abs_path = project_root / rel
        if abs_path.is_file():
            yield rel, abs_path


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
    bad = [p for p in existing if "\n" in p]
    if bad:
        raise GitError(
            f"hash_object cannot handle paths containing newlines: {bad!r}. "
            "git hash-object --stdin-paths is newline-delimited and has no -z variant."
        )
    stdin = "\n".join(str(project_root / p) for p in existing)
    out = _git(project_root, "hash-object", "--stdin-paths", input_text=stdin)
    hashes = out.splitlines()
    return dict(zip(existing, hashes, strict=True))


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
        raw = file_path.read_bytes()
        if b"\x00" in raw:
            # Match git's behavior on the prior-blob path for binary content.
            return f"Binary files /dev/null and b/{rel_path} differ\n"
        return _format_synthetic_diff(rel_path, "", raw.decode("utf-8", errors="replace"))
    if not file_exists:
        try:
            raw = subprocess.run(
                ["git", "show", blob],
                cwd=project_root,
                capture_output=True,
                check=True,
            ).stdout
        except FileNotFoundError as e:
            raise GitError("git executable not found in PATH") from e
        except subprocess.CalledProcessError as e:
            raise GitError(
                f"git show {blob} failed (exit {e.returncode}): "
                f"{e.stderr.decode('utf-8', errors='replace').strip()}"
            ) from e
        if b"\x00" in raw:
            return f"Binary files a/{rel_path} and /dev/null differ\n"
        return _format_synthetic_diff(rel_path, raw.decode("utf-8", errors="replace"), "")
    return _git(project_root, "diff", blob, "--", rel_path)


def _format_synthetic_diff(rel_path: str, old: str, new: str) -> str:
    """Unified diff for the no-prior or deleted-file cases.

    Uses difflib.unified_diff for proper '@@' hunk headers, and appends
    the '\\ No newline at end of file' marker where the source content
    didn't end with a newline (matching git's output).
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    out = []
    for line in difflib.unified_diff(
        old_lines, new_lines, fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}"
    ):
        if line.endswith("\n"):
            out.append(line)
        else:
            out.append(line + "\n\\ No newline at end of file\n")
    return "".join(out)
