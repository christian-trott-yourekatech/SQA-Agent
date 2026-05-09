"""Tests for anchor format, regex, insertion, removal."""

import pytest

from sqa_tool import anchors


def test_parse_ids_python():
    assert anchors.parse_ids("# sqa: K7M3X") == ["K7M3X"]
    assert anchors.parse_ids("# sqa: K7M3X, A4B7P") == ["K7M3X", "A4B7P"]


def test_parse_ids_multiple_styles():
    assert anchors.parse_ids("// sqa: ABCDE") == ["ABCDE"]
    assert anchors.parse_ids("<!-- sqa: ABCDE, FGHIJ -->") == ["ABCDE", "FGHIJ"]
    assert anchors.parse_ids("/* sqa: ABCDE */") == ["ABCDE"]
    assert anchors.parse_ids("-- sqa: ABCDE") == ["ABCDE"]


def test_parse_ids_no_match():
    assert anchors.parse_ids("just some text") == []
    assert anchors.parse_ids("# sqa: lowercase") == []
    assert anchors.parse_ids("# sqa: ABC") == []  # too short


def test_parse_ids_inline_with_code():
    line = "x = 1  # sqa: ABCDE"
    assert anchors.parse_ids(line) == ["ABCDE"]


def test_parse_ids_multiline():
    text = """\
# sqa: AAAAA
def f():
    pass  # sqa: BBBBB, CCCCC
"""
    assert anchors.parse_ids(text) == ["AAAAA", "BBBBB", "CCCCC"]


def test_comment_for_python(tmp_path):
    path = tmp_path / "x.py"
    assert anchors.comment_for(path, "sqa: AAAAA") == "# sqa: AAAAA"


def test_comment_for_javascript(tmp_path):
    assert anchors.comment_for(tmp_path / "x.js", "sqa: A") == "// sqa: A"


def test_comment_for_html_block(tmp_path):
    assert anchors.comment_for(tmp_path / "x.html", "sqa: A") == "<!-- sqa: A -->"


def test_comment_for_sqa_md(tmp_path):
    assert anchors.comment_for(tmp_path / ".sqa.md", "sqa: A") == "<!-- sqa: A -->"


def test_comment_for_sql(tmp_path):
    assert anchors.comment_for(tmp_path / "x.sql", "sqa: A") == "-- sqa: A"


def test_is_commentable(tmp_path):
    assert anchors.is_commentable(tmp_path / "x.py")
    assert anchors.is_commentable(tmp_path / ".sqa.md")
    assert anchors.is_commentable(tmp_path / "auth/.sqa.md")
    assert not anchors.is_commentable(tmp_path / "data.json")


def test_insert_anchor_new_file(tmp_path):
    path = tmp_path / ".sqa.md"
    anchors.insert_anchor(path, "ABCDE")
    assert path.read_text() == "<!-- sqa: ABCDE -->\n"


def test_insert_anchor_appends_when_anchors_exist(tmp_path):
    path = tmp_path / ".sqa.md"
    path.write_text("<!-- sqa: AAAAA -->\n")
    anchors.insert_anchor(path, "BBBBB")
    text = path.read_text()
    assert "AAAAA" in text
    assert "BBBBB" in text
    assert text.count("<!-- sqa:") == 2


def test_insert_anchor_python_no_shebang(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("def f():\n    pass\n")
    anchors.insert_anchor(path, "ABCDE")
    assert path.read_text().startswith("# sqa: ABCDE\n")


def test_insert_anchor_python_with_shebang(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("#!/usr/bin/env python\ndef f():\n    pass\n")
    anchors.insert_anchor(path, "ABCDE")
    text_after = path.read_text()
    assert text_after.startswith("#!/usr/bin/env python\n# sqa: ABCDE\n")


def test_insert_anchor_un_commentable_raises(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("{}")
    with pytest.raises(ValueError):
        anchors.insert_anchor(path, "ABCDE")


def test_insert_anchor_invalid_id_raises(tmp_path):
    # Invalid finding IDs (wrong length, bad characters, lowercase) must be
    # rejected before any file I/O. Pin down the ValueError so this branch
    # in insert_anchor isn't lost in a future refactor.
    path = tmp_path / "x.py"
    path.write_text("def f():\n    pass\n")
    with pytest.raises(ValueError):
        anchors.insert_anchor(path, "bad")
    with pytest.raises(ValueError):
        anchors.insert_anchor(path, "abcde")  # lowercase
    with pytest.raises(ValueError):
        anchors.insert_anchor(path, "ABCDEF")  # too long


def test_remove_anchor_drops_line_when_only_id(tmp_path):
    path = tmp_path / ".sqa.md"
    path.write_text("<!-- sqa: AAAAA -->\nsome text\n")
    assert anchors.remove_anchor(path, "AAAAA") is True
    assert path.read_text() == "some text\n"


def test_remove_anchor_preserves_other_ids(tmp_path):
    path = tmp_path / ".sqa.md"
    path.write_text("<!-- sqa: AAAAA, BBBBB, CCCCC -->\n")
    assert anchors.remove_anchor(path, "BBBBB") is True
    txt = path.read_text()
    assert "AAAAA" in txt
    assert "BBBBB" not in txt
    assert "CCCCC" in txt


def test_remove_anchor_no_match(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("# nothing here\n")
    assert anchors.remove_anchor(path, "AAAAA") is False


def test_remove_anchor_nonexistent_path_returns_false(tmp_path):
    # remove_anchor on a path that doesn't exist should silently return False
    # rather than raising — covers the early-exit branch.
    path = tmp_path / "does_not_exist.py"
    assert anchors.remove_anchor(path, "AAAAA") is False
    # And the file should still not exist (no side effects).
    assert not path.exists()


def test_remove_anchor_id_not_in_anchor_line(tmp_path):
    # Anchor exists in the file but the requested ID isn't in any anchor —
    # exercises the kept == ids branch (no change, returns False).
    path = tmp_path / "x.py"
    original = "# sqa: AAAAA\nx = 1\n"
    path.write_text(original)
    assert anchors.remove_anchor(path, "BBBBB") is False
    # File contents unchanged.
    assert path.read_text() == original


def test_remove_anchor_preserves_code_on_inline_comment_python(tmp_path):
    # Regression test for finding 2DD7I: removing the last ID from an inline
    # comment must not delete the code that precedes it.
    path = tmp_path / "x.py"
    path.write_text("x = 1  # sqa: ABCDE\ny = 2\n")
    assert anchors.remove_anchor(path, "ABCDE") is True
    assert path.read_text() == "x = 1\ny = 2\n"


def test_remove_anchor_preserves_code_on_inline_comment_js(tmp_path):
    path = tmp_path / "x.js"
    path.write_text("const x = 1; // sqa: ABCDE\nconst y = 2;\n")
    assert anchors.remove_anchor(path, "ABCDE") is True
    assert path.read_text() == "const x = 1;\nconst y = 2;\n"


def test_remove_anchor_preserves_code_on_inline_block_comment(tmp_path):
    path = tmp_path / "x.css"
    path.write_text("body { color: red; } /* sqa: ABCDE */\nfoo\n")
    assert anchors.remove_anchor(path, "ABCDE") is True
    assert path.read_text() == "body { color: red; }\nfoo\n"


def test_remove_anchor_preserves_other_ids_on_inline_comment(tmp_path):
    # When other IDs remain, the comment stays — only the matching ID is removed.
    path = tmp_path / "x.py"
    path.write_text("x = 1  # sqa: AAAAA, BBBBB\n")
    assert anchors.remove_anchor(path, "AAAAA") is True
    assert path.read_text() == "x = 1  # sqa: BBBBB\n"


def test_remove_anchor_drops_indented_comment_only_line(tmp_path):
    # Indented comment-only line should still be dropped entirely.
    path = tmp_path / "x.py"
    path.write_text("def f():\n    # sqa: ABCDE\n    return 1\n")
    assert anchors.remove_anchor(path, "ABCDE") is True
    assert path.read_text() == "def f():\n    return 1\n"


def test_find_anchors_in_file(tmp_path):
    path = tmp_path / "x.py"
    path.write_text("# sqa: AAAAA\ndef f(): pass\n# sqa: BBBBB\n")
    assert anchors.find_anchors_in_file(path) == ["AAAAA", "BBBBB"]


def test_find_anchors_in_file_nonexistent_path(tmp_path):
    # Non-existent paths should yield an empty list, not raise.
    path = tmp_path / "does_not_exist.py"
    assert anchors.find_anchors_in_file(path) == []


def test_find_anchors_for_orphan_scan_nonexistent_path(tmp_path):
    # Non-existent paths should yield an empty list, not raise.
    path = tmp_path / "does_not_exist.py"
    assert anchors.find_anchors_for_orphan_scan(path) == []


def test_find_anchors_for_orphan_scan_python_skips_strings(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_text("# sqa: REALA\nparse_ids(\"# sqa: FAKEA\")\nx = '''\n# sqa: FAKEB\n'''\n")
    assert anchors.find_anchors_for_orphan_scan(path) == ["REALA"]


def test_find_anchors_for_orphan_scan_python_finds_real_alongside_fixtures(tmp_path):
    path = tmp_path / "fixture.py"
    path.write_text('def test():\n    s = "# sqa: FAKEA"\n    return s  # sqa: REALA\n')
    assert anchors.find_anchors_for_orphan_scan(path) == ["REALA"]


def test_find_anchors_for_orphan_scan_md_skips_fenced_block(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "Real anchor on next line:\n"
        "<!-- sqa: REALA -->\n"
        "\n"
        "Example:\n"
        "```python\n"
        "# sqa: FAKEA\n"
        "```\n"
        "\n"
        "Tilde fence:\n"
        "~~~\n"
        "# sqa: FAKEB\n"
        "~~~\n"
    )
    assert anchors.find_anchors_for_orphan_scan(path) == ["REALA"]


def test_find_anchors_for_orphan_scan_md_skips_inline_code(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("Use `# sqa: FAKEA` to anchor.\n<!-- sqa: REALA -->\n")
    assert anchors.find_anchors_for_orphan_scan(path) == ["REALA"]


def test_find_anchors_for_orphan_scan_other_suffix_unchanged(tmp_path):
    # Files without .py/.md/.markdown get raw parse_ids — strings aren't stripped.
    path = tmp_path / "data.txt"
    path.write_text('"# sqa: SHOWN"\n# sqa: ALSOA\n')
    assert anchors.find_anchors_for_orphan_scan(path) == ["SHOWN", "ALSOA"]


def test_strip_python_strings_blanks_string_contents():
    text = '# sqa: KEEP\nx = "# sqa: GONE"\n'
    stripped = anchors._strip_python_strings(text)
    assert "KEEP" in stripped
    assert "GONE" not in stripped


def test_strip_python_strings_invalid_python_returns_input():
    bad = "def (\n# sqa: KEEP\n"
    assert anchors._strip_python_strings(bad) == bad


def test_strip_python_strings_blanks_fstring_literal_segments():
    text = '# sqa: KEEP\nx = f"# sqa: GONEX, {value}"\n'
    stripped = anchors._strip_python_strings(text)
    assert "KEEP" in stripped
    assert "GONEX" not in stripped


def test_strip_markdown_code_blocks_handles_both_fences():
    text = "before\n```\n# sqa: GONEA\n```\nbetween\n~~~\n# sqa: GONEB\n~~~\n<!-- sqa: KEEP -->\n"
    stripped = anchors._strip_markdown_code_blocks(text)
    assert "GONEA" not in stripped
    assert "GONEB" not in stripped
    assert "KEEP" in stripped


def test_strip_markdown_inline_code_blanks_backtick_spans():
    text = "Use `# sqa: GONE` here. <!-- sqa: KEEP -->\n"
    stripped = anchors._strip_markdown_inline_code(text)
    assert "GONE" not in stripped
    assert "KEEP" in stripped
