"""Thin wrappers over git commands used by sqa-tool.

Predicate convention: boolean predicates in this module (``is_repo``,
``has_commits``) treat any ``GitError`` — including "git executable not
found" — as "no". Callers that need to distinguish infrastructure failure
from a negative answer must call ``_git`` directly.
"""

import difflib
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, overload


class GitError(RuntimeError):
    """Raised when a git invocation fails or the directory isn't a git repo."""


def _git(project_root: Path, *args: str, input_text: str | None = None) -> str:
    """Run `git <args>` in text mode and return stdout. See `_run_git` for the encoding contract."""
    return _run_git(project_root, args, input_data=input_text, binary=False).stdout


def _git_bytes(project_root: Path, *args: str) -> bytes:
    """Run `git <args>` and return raw stdout bytes.

    Used when stdout may not be valid UTF-8 (e.g. binary blobs from `git
    show`). See `_run_git` for the encoding/error contract.
    """
    return _run_git(project_root, args, binary=True).stdout


@overload
def _run_git(
    project_root: Path,
    args: tuple[str, ...],
    *,
    input_data: str | None = ...,
    binary: Literal[False] = ...,
) -> "subprocess.CompletedProcess[str]": ...


@overload
def _run_git(
    project_root: Path,
    args: tuple[str, ...],
    *,
    input_data: None = ...,
    binary: Literal[True],
) -> "subprocess.CompletedProcess[bytes]": ...


def _run_git(
    project_root: Path,
    args: tuple[str, ...],
    *,
    input_data: str | None = None,
    binary: bool = False,
) -> "subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]":
    """Shared subprocess wrapper for `_git` / `_git_bytes`. Raises `GitError`.

    When `binary=False`, stdout is decoded as UTF-8 strictly; non-UTF-8
    bytes raise UnicodeDecodeError at the subprocess boundary. On failure,
    stderr is decoded as UTF-8 with `errors='replace'` so the `GitError`
    construction itself cannot raise a secondary decode error.
    """
    # Internal invariant matching the @overload contract: binary stdin is
    # not supported. Without this guard, passing input_data with
    # binary=True would surface as an opaque TypeError from subprocess
    # (text=False expects bytes, not str). If a binary-stdin caller ever
    # appears, widen input_data to 'str | bytes | None' instead.
    assert not (binary and input_data is not None), (
        "_run_git does not support input_data with binary=True; "
        "widen input_data to bytes if a binary-stdin caller is needed."
    )
    try:
        return subprocess.run(
            ["git", *args],
            cwd=project_root,
            input=input_data,
            capture_output=True,
            text=not binary,
            encoding=None if binary else "utf-8",
            check=True,
        )
    except FileNotFoundError as e:
        raise GitError("git executable not found in PATH") from e
    except subprocess.CalledProcessError as e:
        stderr = e.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise GitError(
            f"git {' '.join(args)} failed (exit {e.returncode}): {stderr.strip()}"
        ) from e


def is_repo(project_root: Path) -> bool:
    """True iff project_root is inside a git working tree."""
    try:
        out = _git(project_root, "rev-parse", "--is-inside-work-tree")
    except GitError:
        # See module docstring: GitError -> False (predicate convention).
        return False
    return out.strip() == "true"


def has_commits(project_root: Path) -> bool:
    """True iff HEAD resolves to a commit."""
    try:
        _git(project_root, "rev-parse", "HEAD")
    except GitError:
        # See module docstring: GitError -> False (predicate convention).
        return False
    return True


def ls_files(project_root: Path) -> list[str]:
    """Return project-relative paths of all git-tracked files in the project root.

    Uses NUL-delimited output (`-z`) so paths containing whitespace, embedded
    quotes, or other shell-special characters are returned verbatim rather
    than in git's C-style quoted form. Path bytes are decoded as UTF-8
    (strict) via `_git`, so paths with non-UTF-8 bytes raise
    UnicodeDecodeError at the subprocess boundary — the project assumes
    UTF-8-encoded source repositories throughout.
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

    Raises `GitError` if `project_root` isn't a git working tree (via the
    underlying `ls_files` call), matching the module-wide convention.
    """
    for rel in ls_files(project_root):
        abs_path = project_root / rel
        if abs_path.is_file():
            yield rel, abs_path


def hash_object(project_root: Path, rel_paths: list[str]) -> dict[str, str]:
    """Compute git blob hashes for a list of project-relative paths.

    Uses a single `git hash-object --stdin-paths` invocation. Paths that do
    not exist at filter time are omitted from the returned dict. Paths that
    vanish between the existence check and git reading them from stdin
    surface as `GitError` rather than being silently dropped.
    """
    if not rel_paths:
        return {}
    # Validate against newlines on the original input, *before* the
    # existence filter — otherwise a non-existent path containing a
    # newline would silently slip through (filtered out before the
    # check) and the error would never surface.
    bad = [p for p in rel_paths if "\n" in p]
    if bad:
        raise GitError(
            f"hash_object cannot handle paths containing newlines: {bad!r}. "
            "git hash-object --stdin-paths is newline-delimited and has no -z variant."
        )
    # Best-effort: paths that vanish between the caller assembling the
    # list and this call are silently dropped from the returned dict.
    # Callers that need completeness must check the returned dict
    # against their input (mark_reviewed and needs_review both do).
    existing = [p for p in rel_paths if (project_root / p).exists()]
    if not existing:
        return {}
    # Pass relative paths verbatim — _run_git sets cwd=project_root, so
    # git hash-object resolves them correctly, and input/output paths
    # match without an extra normalization step.
    stdin = "\n".join(existing)
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
        # No prior blob and no file on disk — nothing to diff. Callers
        # (diff_since_review) validate this upfront and error before
        # calling; this branch is a safety net so this function never
        # raises on a degenerate input.
        return ""
    # Design note: the added/removed branches use difflib rather than git
    # so this function does no filesystem or git-object setup beyond
    # reading the on-disk file (no temp files, no `git diff --no-index`
    # plumbing). The modify case delegates to `git diff` for byte-exact
    # output on the dominant path. The synthetic-diff headers and the
    # "\ No newline at end of file" marker are formatted in
    # _format_synthetic_diff to stay close to git's output.
    if not blob:
        return _synthetic_side_diff(rel_path, file_path.read_bytes(), "added")
    if not file_exists:
        raw = _git_bytes(project_root, "show", blob)
        return _synthetic_side_diff(rel_path, raw, "removed")
    return _git(project_root, "diff", blob, "--", rel_path)


def _synthetic_side_diff(rel_path: str, raw: bytes, side: Literal["added", "removed"]) -> str:
    """Render a synthetic unified diff for the added- or removed-side cases.

    Returns git's 'Binary files ... differ' marker for content that looks
    binary (NUL heuristic) or that fails strict UTF-8 decode — the second
    case covers non-UTF-8 text (e.g. latin-1) that the NUL heuristic
    doesn't flag but still can't be rendered as a synthetic text diff.
    Otherwise returns a unified diff with the decoded content placed on
    the appropriate side.
    """
    marker = _binary_diff_marker(raw, rel_path, side=side)
    if marker is not None:
        return marker
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _format_binary_marker(rel_path, side=side)
    if side == "added":
        return _format_synthetic_diff(rel_path, "", decoded)
    return _format_synthetic_diff(rel_path, decoded, "")


def _binary_diff_marker(
    raw: bytes,
    rel_path: str,
    *,
    side: Literal["added", "removed"],
) -> str | None:
    """Return git's 'Binary files ... differ' line if `raw` looks binary, else None.

    Uses a NUL-byte heuristic, which diverges from git's richer detection
    (which inspects the first ~8000 bytes for NULs and various
    non-printable characters). Callers that have separately determined
    the content can't be rendered as text — for instance, because a
    UTF-8 strict decode raised UnicodeDecodeError — should call
    ``_format_binary_marker`` directly to bypass the heuristic.
    """
    if b"\x00" not in raw:
        return None
    return _format_binary_marker(rel_path, side=side)


def _format_binary_marker(rel_path: str, *, side: Literal["added", "removed"]) -> str:
    """Format git's 'Binary files ... differ' line for the synthetic-diff branches."""
    if side == "added":
        return f"Binary files /dev/null and b/{rel_path} differ\n"
    return f"Binary files a/{rel_path} and /dev/null differ\n"


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
