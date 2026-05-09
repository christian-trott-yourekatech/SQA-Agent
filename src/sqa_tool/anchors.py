"""Anchor format, per-language comment syntax, regex matching, insertion, and removal."""

import fcntl
import io
import os
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
# A negative lookbehind ensures we don't match when 'sqa:' is preceded by a
# word character (e.g. 'foosqa: ABCDE'), so the anchor must be at a word
# boundary (start of string or after a non-word character like '#', '//', etc.).
ANCHOR_RE = re.compile(
    r"(?<![A-Za-z0-9_])sqa:\s*(?P<ids>[A-Z2-7]{" + str(ID_LENGTH) + r"}"
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

    Acquires an exclusive `fcntl.flock` on `path` for the duration of the
    read+write so concurrent `insert_anchor` / `remove_anchor` calls on the
    same file can't clobber each other.

    Strategy:
      - If the file already contains `sqa:`, append a fresh comment line at end.
      - Otherwise, prepend at the top — after a shebang line if present.
      - Empty/just-created files receive only the anchor line.

    The "already contains `sqa:`" check uses the raw regex and intentionally
    does *not* skip string-literal or fenced-code-block contents the way
    `find_anchors_for_orphan_scan` does. The placement choice here is a
    cosmetic heuristic — being too eager (appending at EOF when the only
    `sqa:` occurrences live inside test fixtures or doc examples) still
    produces a working anchor, while orphan-scanning needs strict context
    awareness to avoid false positives.
    """
    if not is_valid_id(finding_id):
        raise ValueError(f"Invalid finding ID: {finding_id!r}")
    if not is_commentable(path):
        raise ValueError(f"Cannot insert anchor in un-commentable file: {path}")

    comment = comment_for(path, f"sqa: {finding_id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        text = path.read_text()
        if not text:
            path.write_text(comment + "\n")
            return
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
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _comment_style(path: Path) -> tuple[str, str | None]:
    """Return (opener, closer) for the comment syntax of `path`.

    `closer` is `None` for line-style comments (which extend to end of line);
    a string for block-style comments (HTML/CSS).
    Raises ValueError if the file extension isn't a known commentable type.
    """
    if path.name == ".sqa.md":
        return ("<!--", "-->")
    ext = _ext(path)
    if ext in _LINE_PREFIX:
        return (_LINE_PREFIX[ext], None)
    if ext in _BLOCK_DELIMS:
        open_, close_ = _BLOCK_DELIMS[ext]
        return (open_, close_)
    raise ValueError(f"Unknown comment style for {path}")


def _comment_extent(
    line: str, anchor_start: int, opener: str | None, closer: str | None
) -> tuple[int, int] | None:
    """Find the (start, end) span of the comment containing the anchor.

    `start` points at the first character of the opener; `end` is one past
    the last character of the closer (for block comments) or at the position
    just before the line-ending characters (for line comments).
    Returns None if the comment can't be located.
    """
    line_end = len(line)
    if line.endswith("\r\n"):
        line_end -= 2
    elif line.endswith("\n"):
        line_end -= 1

    if opener is not None and closer is None:
        # Line-style comment: opener to end of line.
        op_pos = line.rfind(opener, 0, anchor_start)
        if op_pos != -1:
            return (op_pos, line_end)
        return None
    if opener is not None and closer is not None:
        op_pos = line.rfind(opener, 0, anchor_start)
        cl_pos = line.find(closer, anchor_start)
        if op_pos != -1 and cl_pos != -1:
            return (op_pos, cl_pos + len(closer))
        return None

    # Heuristic fallback when the file's comment style isn't known: try
    # block-comment pairs first (they're unambiguous), then line prefixes.
    for op, cl in (("<!--", "-->"), ("/*", "*/")):
        op_pos = line.rfind(op, 0, anchor_start)
        cl_pos = line.find(cl, anchor_start)
        if op_pos != -1 and cl_pos != -1:
            return (op_pos, cl_pos + len(cl))
    for prefix in ("//", "--", "#"):
        op_pos = line.rfind(prefix, 0, anchor_start)
        if op_pos != -1:
            return (op_pos, line_end)
    return None


def remove_anchor(path: Path, finding_id: str) -> bool:
    """Remove a single finding ID from any anchor comment in `path`.

    When the removed ID was the only one in the comment:
    - If the comment is on a line by itself (preceded only by whitespace),
      the entire line is removed.
    - If the line has code before the comment (e.g. `x = 1  # sqa: ABCDE`),
      only the comment is removed; the code is preserved with trailing
      whitespace trimmed.

    Acquires an exclusive `fcntl.flock` on `path` for the duration of the
    read+write so concurrent `insert_anchor` / `remove_anchor` calls on the
    same file can't clobber each other.

    Returns True if anything was changed.
    """
    if not path.exists():
        return False
    try:
        fd = os.open(path, os.O_RDWR)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return _remove_anchor_locked(path, finding_id)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _remove_anchor_locked(path: Path, finding_id: str) -> bool:
    text = path.read_text()

    try:
        opener, closer = _comment_style(path)
    except ValueError:
        # Unknown extension — fall back to context-only heuristics.
        opener, closer = None, None

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
        if kept:
            # Some IDs remain — rewrite just the IDs section, preserve everything else.
            new_ids = ", ".join(kept)
            new_line = line[: m.start("ids")] + new_ids + line[m.end("ids") :]
            new_lines.append(new_line)
            continue

        # Last ID gone — strip the comment delimiters and decide what to do
        # with the remainder of the line.
        extent = _comment_extent(line, m.start(), opener, closer)
        if extent is None:
            # Couldn't locate the comment delimiters — least-destructive
            # fallback is to leave the line and just empty the IDs.
            new_line = line[: m.start("ids")] + line[m.end("ids") :]
            new_lines.append(new_line)
            continue
        comment_start, comment_end = extent
        before = line[:comment_start]
        after = line[comment_end:]  # typically just '\n' or ''
        if before.strip() == "":
            # Comment-only line (modulo whitespace) — drop entirely.
            continue
        # Line had code before the anchor comment — preserve the code,
        # trim the trailing whitespace that lived between code and comment.
        new_lines.append(before.rstrip(" \t") + after)

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
