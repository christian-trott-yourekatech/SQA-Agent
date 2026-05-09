"""Integration tests: run CLI subcommands against a real temp project."""

import json
import os
import subprocess
from pathlib import Path

from sqa_tool.cli import main as cli_main


def _run(project: Path, *argv: str, expected_exit: int = 0) -> int:
    cwd = Path.cwd()
    os.chdir(project)
    try:
        rc = cli_main(list(argv))
    finally:
        os.chdir(cwd)
    if expected_exit is not None:
        assert rc == expected_exit, f"sqa-tool {' '.join(argv)} exited {rc}"
    return rc


def _capture(project: Path, *argv: str, capsys=None) -> str:
    if capsys is None:
        raise RuntimeError("capsys fixture required")
    capsys.readouterr()  # drain prior
    _run(project, *argv)
    return capsys.readouterr().out


def test_init(project: Path):
    _run(project, "init")
    assert (project / ".sqa" / "config.toml").exists()
    assert (project / ".sqa" / "findings").is_dir()
    assert (project / ".sqa" / "file_status.json").exists()


def test_init_scaffolds_skills_and_agents(project: Path):
    _run(project, "init")
    skills_dir = project / ".claude" / "skills"
    agents_dir = project / ".claude" / "agents"
    assert skills_dir.is_dir()
    assert agents_dir.is_dir()
    # Each skill is its own directory containing SKILL.md.
    assert (skills_dir / "sqa-review" / "SKILL.md").is_file()
    assert (skills_dir / "sqa-resolve" / "SKILL.md").is_file()
    assert (skills_dir / "sqa-status" / "SKILL.md").is_file()
    # Subagents are flat .md files.
    assert (agents_dir / "review-file.md").is_file()
    assert (agents_dir / "triage-file.md").is_file()
    assert (agents_dir / "resolve-file.md").is_file()
    assert (agents_dir / "fix-orphans.md").is_file()


def test_init_does_not_overwrite_existing_skill(project: Path):
    # Pre-create a skill directory with custom content.
    skills_dir = project / ".claude" / "skills" / "sqa-review"
    skills_dir.mkdir(parents=True)
    custom = skills_dir / "SKILL.md"
    custom.write_text("# my customized version\n")
    _run(project, "init")
    # Custom content preserved.
    assert custom.read_text() == "# my customized version\n"
    # Other skills still installed.
    assert (project / ".claude" / "skills" / "sqa-resolve" / "SKILL.md").is_file()


def test_init_refuses_overwrite(project: Path):
    _run(project, "init")
    rc = _run(project, "init", expected_exit=1)
    assert rc == 1


def test_record_and_show_finding(initialized: Path, capsys):
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=Use isinstance instead of type()",
        "--severity=warning",
        "--related=src/sample.py",
    )
    fid = capsys.readouterr().out.strip()
    assert len(fid) == 5
    capsys.readouterr()
    _run(initialized, "show-finding", fid)
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == fid
    assert payload["message"] == "Use isinstance instead of type()"
    assert payload["severity"] == "warning"
    assert payload["status"] == "open"
    assert payload["triage"] is None
    assert payload["related_files"] == ["src/sample.py"]


def test_record_finding_with_anchor_in_sqa_md(initialized: Path, capsys):
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=Module is overcomplicated",
        "--anchor=src/.sqa.md",
        "--related=src/sample.py",
    )
    fid = capsys.readouterr().out.strip()
    md = (initialized / "src" / ".sqa.md").read_text()
    assert f"sqa: {fid}" in md


def test_record_finding_anchor_uncommentable_fails(initialized: Path, capsys):
    (initialized / "data.json").write_text("{}")
    capsys.readouterr()
    rc = _run(
        initialized,
        "record-finding",
        "--message=bad",
        "--anchor=data.json",
        expected_exit=1,
    )
    assert rc == 1
    # No leftover finding should remain.
    fdir = initialized / ".sqa" / "findings"
    assert list(fdir.iterdir()) == []


def test_list_findings_filters(initialized: Path, capsys):
    # Record three findings with different triage states.
    capsys.readouterr()
    _run(initialized, "record-finding", "--message=A", "--severity=info")
    a_id = capsys.readouterr().out.strip()
    _run(initialized, "record-finding", "--message=B", "--severity=info")
    b_id = capsys.readouterr().out.strip()
    _run(initialized, "record-finding", "--message=C", "--severity=info")
    c_id = capsys.readouterr().out.strip()

    _run(initialized, "triage", a_id, "auto", "--rationale=easy fix")
    _run(initialized, "triage", b_id, "ignore", "--rationale=intentional")

    capsys.readouterr()
    _run(initialized, "list-findings")
    all_findings = json.loads(capsys.readouterr().out)
    assert len(all_findings) == 3

    capsys.readouterr()
    _run(initialized, "list-findings", "--triage=auto")
    auto = json.loads(capsys.readouterr().out)
    assert len(auto) == 1
    assert auto[0]["id"] == a_id

    capsys.readouterr()
    _run(initialized, "list-findings", "--triage=untriaged")
    untriaged = json.loads(capsys.readouterr().out)
    assert len(untriaged) == 1
    assert untriaged[0]["id"] == c_id

    capsys.readouterr()
    _run(initialized, "list-findings", "--count")
    assert capsys.readouterr().out.strip() == "3"

    capsys.readouterr()
    _run(initialized, "list-findings", "--limit=2")
    limited = json.loads(capsys.readouterr().out)
    assert len(limited) == 2


def test_status(initialized: Path, capsys):
    capsys.readouterr()
    _run(initialized, "record-finding", "--message=x", "--severity=warning")
    fid = capsys.readouterr().out.strip()
    _run(initialized, "triage", fid, "auto", "--rationale=easy")

    capsys.readouterr()
    _run(initialized, "status")
    s = json.loads(capsys.readouterr().out)
    assert s["total"] == 1
    assert s["by_triage"]["auto"] == 1
    assert s["by_severity"]["warning"] == 1
    assert s["by_status"]["open"] == 1


def _set_include_globs(project: Path, *patterns: str) -> None:
    cfg = project / ".sqa" / "config.toml"
    text = cfg.read_text()
    new = []
    for line in text.splitlines():
        if line.strip().startswith("include ="):
            new.append("include = [" + ", ".join(f'"{p}"' for p in patterns) + "]")
        else:
            new.append(line)
    cfg.write_text("\n".join(new) + "\n")


def test_needs_review_initial_lists_all(initialized: Path, capsys):
    _set_include_globs(initialized, "src/**/*.py")
    capsys.readouterr()
    _run(initialized, "needs-review")
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["src/sample.py"]


def test_needs_review_count(initialized: Path, capsys):
    _set_include_globs(initialized, "src/**/*.py")
    capsys.readouterr()
    _run(initialized, "needs-review", "--count")
    assert capsys.readouterr().out.strip() == "1"


def test_mark_reviewed_then_needs_review_empty(initialized: Path, capsys):
    _set_include_globs(initialized, "src/**/*.py")
    _run(initialized, "mark-reviewed", "src/sample.py")
    capsys.readouterr()
    _run(initialized, "needs-review", "--count")
    assert capsys.readouterr().out.strip() == "0"


def test_needs_review_after_edit(initialized: Path, capsys):
    _set_include_globs(initialized, "src/**/*.py")
    _run(initialized, "mark-reviewed", "src/sample.py")
    # Edit file
    (initialized / "src" / "sample.py").write_text("def hello(): return 'edited'\n")
    capsys.readouterr()
    _run(initialized, "needs-review")
    assert capsys.readouterr().out.strip() == "src/sample.py"


def test_resolve_removes_anchor(initialized: Path, capsys):
    sub = subprocess.run
    # Insert an anchor in the source file via record-finding's --anchor flow.
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=fix me",
        "--anchor=src/sample.py",
    )
    fid = capsys.readouterr().out.strip()
    assert f"sqa: {fid}" in (initialized / "src" / "sample.py").read_text()
    # Commit so git tracks the anchor.
    sub(["git", "add", "."], cwd=initialized, check=True, capture_output=True)
    sub(
        ["git", "commit", "-q", "-m", "anchor"],
        cwd=initialized,
        check=True,
        capture_output=True,
    )
    _run(initialized, "resolve", fid, "--rationale=fixed it")
    assert f"sqa: {fid}" not in (initialized / "src" / "sample.py").read_text()


def test_findings_for_file_includes_ancestor_scope(initialized: Path, capsys):
    # Create a file-scope finding directly anchored in src/.sqa.md with related src/sample.py.
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=Module-level concern",
        "--anchor=src/.sqa.md",
        "--related=src/sample.py",
    )
    module_id = capsys.readouterr().out.strip()
    # Create a file-scope finding directly anchored in src/sample.py.
    capsys.readouterr()
    _run(
        initialized,
        "record-finding",
        "--message=File-level concern",
        "--anchor=src/sample.py",
    )
    file_id = capsys.readouterr().out.strip()

    capsys.readouterr()
    _run(initialized, "findings-for-file", "src/sample.py")
    items = json.loads(capsys.readouterr().out)
    ids = {it["id"] for it in items}
    assert module_id in ids
    assert file_id in ids
