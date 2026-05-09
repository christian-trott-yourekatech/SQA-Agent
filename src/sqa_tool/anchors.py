"""Anchor format, per-language comment syntax, regex matching, insertion, and removal."""

import re
from pathlib import Path

from sqa_tool.findings import ID_LENGTH, is_valid_id

# Map file extension (lowercased, no dot) → comment style.
# Line styles: a single string is the line-comment prefix.
# Block styles: a 2-tuple (open, close).
_LINE_PREFIX: dict[str, str] = {
    "py": "#",
    "sh": "#",
    "bash": "#",
    "zsh": "#",
    "rb": "#",
    "yaml": "#",
    "yml": "#",
    "toml": "#",
    "ini": "#",
    "cfg": "#",
    "conf": "#",
    "js": "//",
    "mjs": "//",
    "cjs": "//",
    "ts": "//",
    "tsx": "//",
    "jsx": "//",
    "go": "//",
    "rs": "//",
    "c": "//",
    "h": "//",
    "cpp": "//",
    "hpp": "//",
    "cc": "//",
    "java": "//",
    "kt": "//",
    "swift": "//",
    "sql": "--",
    "lua": "--",
    "hs": "--",
}
_BLOCK_DELIMS: dict[str, tuple[str, str]] = {
    "css": ("/*", "*/"),
    "scss": ("/*", "*/"),
    "html": ("<!--", "-->"),
    "htm": ("<!--", "-->"),
    "xml": ("<!--", "-->"),
    "md": ("<!--", "-->"),
    "markdown": ("<!--", "-->"),
}

# Files we know we can't comment in (source-of-truth for "un-commentable").
_UNCOMMENTABLE_EXTS = {"json", "csv", "tsv"}


def _ext(path: Path) -> str:
    return path.suffix.lstrip(".").lower()


def is_commentable(path: Path) -> bool:
    """True if the tool knows how to insert an anchor comment in this file type."""
    ext = _ext(path)
    if ext in _UNCOMMENTABLE_EXTS:
        return False
    return ext in _LINE_PREFIX or ext in _BLOCK_DELIMS or path.name == ".sqa.md"


def comment_for(path: Path, body: str) -> str:
    """Format `body` as a comment appropriate for the file's language.

    `.sqa.md` is treated as markdown (block-style)."""
    if path.name == ".sqa.md":
        return f"<!-- {body} -->"
    ext = _ext(path)
    if ext in _LINE_PREFIX:
        return f"{_LINE_PREFIX[ext]} {body}"
    if ext in _BLOCK_DELIMS:
        open_, close_ = _BLOCK_DELIMS[ext]
        return f"{open_} {body} {close_}"
    raise ValueError(f"Don't know how to format a comment for {path}")


# Match `sqa: <id>` or `sqa: <id>, <id>, ...` in any comment style.
# The comment delimiters themselves are not part of the match.
ANCHOR_RE = re.compile(
    r"sqa:\s*(?P<ids>[A-Z2-7]{" + str(ID_LENGTH) + r"}"
    r"(?:\s*,\s*[A-Z2-7]{" + str(ID_LENGTH) + r"})*)"
)


def parse_ids(text: str) -> list[str]:
    """Extract every finding ID referenced in `text` (any comment style).

    Returns IDs in order of appearance, with duplicates preserved.
    """
    out: list[str] = []
    for m in ANCHOR_RE.finditer(text):
        for part in m.group("ids").split(","):
            cand = part.strip()
            if is_valid_id(cand):
                out.append(cand)
    return out


def insert_anchor(path: Path, finding_id: str) -> None:
    """Insert an anchor comment for `finding_id` into `path`.

    Strategy:
      - If the file already contains `sqa:`, append a fresh comment line at end.
      - Otherwise, prepend at the top — after a shebang line if present.

    The caller is responsible for any locking required around the operation.
    """
    if not is_valid_id(finding_id):
        raise ValueError(f"Invalid finding ID: {finding_id!r}")
    if not is_commentable(path):
        raise ValueError(f"Cannot insert anchor in un-commentable file: {path}")

    comment = comment_for(path, f"sqa: {finding_id}")

    if not path.exists():
        path.write_text(comment + "\n")
        return

    text = path.read_text()
    if ANCHOR_RE.search(text):
        # Append a new line; ensure trailing newline before insert.
        sep = "" if text.endswith("\n") else "\n"
        path.write_text(text + sep + comment + "\n")
        return

    # No prior anchor — prepend, respecting a shebang on line 1.
    lines = text.splitlines(keepends=True)
    insert_at = 0
    if lines and lines[0].startswith("#!"):
        insert_at = 1
    new_text = "".join(lines[:insert_at]) + comment + "\n" + "".join(lines[insert_at:])
    path.write_text(new_text)


def remove_anchor(path: Path, finding_id: str) -> bool:
    """Remove a single finding ID from any anchor comment in `path`.

    If a comment becomes empty (no IDs left), the entire line is removed.
    Returns True if anything was changed.
    """
    if not path.exists():
        return False
    text = path.read_text()
    new_lines: list[str] = []
    changed = False
    for line in text.splitlines(keepends=True):
        m = ANCHOR_RE.search(line)
        if not m:
            new_lines.append(line)
            continue
        ids = [p.strip() for p in m.group("ids").split(",")]
        kept = [i for i in ids if i != finding_id]
        if kept == ids:
            new_lines.append(line)
            continue
        changed = True
        if not kept:
            # Drop the whole line.
            continue
        # Rewrite the matched IDs portion.
        new_ids = ", ".join(kept)
        new_line = line[: m.start("ids")] + new_ids + line[m.end("ids") :]
        new_lines.append(new_line)
    if changed:
        path.write_text("".join(new_lines))
    return changed


def find_anchors_in_file(path: Path) -> list[str]:
    """Return all finding IDs referenced by anchors in `path`."""
    if not path.exists():
        return []
    return parse_ids(path.read_text())
