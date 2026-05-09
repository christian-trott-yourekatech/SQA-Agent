"""Anchor format, per-language comment syntax, regex matching, insertion, and removal."""

import io
import re
import token
import tokenize
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


def _strip_python_strings(text: str) -> str:
    """Replace the contents of Python string literals with blanks.

    Used so that anchor-looking text inside a string (e.g. test fixtures
    like `parse_ids("# sqa: ABCDE")`) isn't picked up as a real anchor.
    Comments are preserved (real anchors live in comments).
    Newlines and overall byte positions are best-effort preserved so error
    spans stay roughly meaningful.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # If the file doesn't tokenize cleanly, fall back to the raw text;
        # the caller will just see the unfiltered anchor matches.
        return text

    # Collect (start_byte_offset, end_byte_offset) ranges for STRING tokens.
    # tokenize gives (row, col) — convert to absolute offsets via line index.
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    def to_offset(row: int, col: int) -> int:
        # tokenize rows are 1-indexed.
        if row - 1 >= len(line_starts):
            return len(text)
        return line_starts[row - 1] + col

    # Blank STRING tokens (regular and triple-quoted literals) and FSTRING_MIDDLE
    # tokens (the literal text segments of an f-string, between {expression} parts).
    # The FSTRING_START/END markers and the embedded {expression} tokens are not
    # blanked — those don't contain literal text that could mask anchors.
    blanked_types = {token.STRING}
    fstring_middle = getattr(token, "FSTRING_MIDDLE", None)
    if fstring_middle is not None:
        blanked_types.add(fstring_middle)

    out_chars = list(text)
    for tok in tokens:
        if tok.type not in blanked_types:
            continue
        start = to_offset(tok.start[0], tok.start[1])
        end = to_offset(tok.end[0], tok.end[1])
        # Blank out non-newline characters inside the string range so that
        # any anchor-looking substring is hidden but offsets/lines stay aligned.
        for i in range(start, min(end, len(out_chars))):
            if out_chars[i] != "\n":
                out_chars[i] = " "
    return "".join(out_chars)


_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})", re.MULTILINE)


_INLINE_CODE_RE = re.compile(r"(?P<ticks>`+)(?P<body>.+?)(?P=ticks)")


def _strip_markdown_inline_code(text: str) -> str:
    """Blank out the contents of inline-code spans (backtick-delimited)."""
    out_chars = list(text)

    def _blank(match: re.Match[str]) -> None:
        body_start = match.start("body")
        body_end = match.end("body")
        for j in range(body_start, body_end):
            if out_chars[j] != "\n":
                out_chars[j] = " "

    for m in _INLINE_CODE_RE.finditer(text):
        _blank(m)
    return "".join(out_chars)


def _strip_markdown_code_blocks(text: str) -> str:
    """Replace the contents of fenced code blocks with blanks.

    Used so that anchor-looking text inside a documentation example
    (a fenced ```...``` block in a .md file) isn't picked up as a real anchor.
    """
    out_chars = list(text)
    in_fence = False
    fence_marker: str | None = None
    lines = text.splitlines(keepends=True)
    pos = 0
    for line in lines:
        stripped = line.lstrip()
        is_fence_line = False
        marker = None
        if stripped.startswith("```") or stripped.startswith("~~~"):
            ch = stripped[0]
            run = 0
            for c in stripped:
                if c == ch:
                    run += 1
                else:
                    break
            marker = ch * run
            is_fence_line = True

        if not in_fence:
            if is_fence_line:
                in_fence = True
                fence_marker = marker
                # The fence line itself is preserved (it's not anchor content).
            # else: regular markdown line — preserved.
        else:
            # We're inside a fenced block.
            if (
                is_fence_line
                and marker is not None
                and fence_marker is not None
                and marker[0] == fence_marker[0]
                and len(marker) >= len(fence_marker)
            ):
                # Closing fence — preserve as-is, exit fence.
                in_fence = False
                fence_marker = None
            else:
                # Blank out non-newline chars inside the fenced block.
                for j in range(pos, pos + len(line)):
                    if out_chars[j] != "\n":
                        out_chars[j] = " "
        pos += len(line)
    return "".join(out_chars)


def find_anchors_for_orphan_scan(path: Path) -> list[str]:
    """Like `find_anchors_in_file`, but skips anchors that live inside
    Python string literals or markdown fenced code blocks.

    This is the function the orphans detector should use: anchors inside
    test fixtures (string literals) or documentation examples (fenced
    code blocks) are intentional non-anchors and should not be reported
    as anchors-without-findings.
    """
    if not path.exists():
        return []
    text = path.read_text()
    suffix = path.suffix.lower()
    if suffix == ".py":
        text = _strip_python_strings(text)
    elif suffix in (".md", ".markdown"):
        text = _strip_markdown_code_blocks(text)
        text = _strip_markdown_inline_code(text)
    return parse_ids(text)
