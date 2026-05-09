"""Integration tests: run CLI subcommands against a real temp project."""

import json
import subprocess
from pathlib import Path

from conftest import _capture, _run

from sqa_tool import findings


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
    # Skills also ship project.md siblings (where applicable).
    assert (skills_dir / "sqa-review" / "project.md").is_file()
    assert (skills_dir / "sqa-resolve" / "project.md").is_file()
    # Subagent framework files (flat .md).
    assert (agents_dir / "review-file.md").is_file()
    assert (agents_dir / "triage-file.md").is_file()
    assert (agents_dir / "resolve-file.md").is_file()
    assert (agents_dir / "fix-orphans.md").is_file()
    # Subagent project files (flat .md, preserved across upgrades).
    assert (agents_dir / "review-file-prompts.md").is_file()
    assert (agents_dir / "triage-file-guidelines.md").is_file()


def test_init_overwrites_framework_skill_md(project: Path):
    """Framework SKILL.md must be overwritten on re-init so users get the
    latest workflow logic."""
    skills_dir = project / ".claude" / "skills" / "sqa-review"
    skills_dir.mkdir(parents=True)
    skill_md = skills_dir / "SKILL.md"
    skill_md.write_text("# stale customization\n")
    _run(project, "init")
    # Stale content is replaced by the bundled framework.
    assert skill_md.read_text() != "# stale customization\n"
    assert "framework" in skill_md.read_text().lower()


def test_init_overwrites_framework_agent_md(project: Path):
    """Framework agent <name>.md must be overwritten on re-init."""
    agents_dir = project / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    agent_md = agents_dir / "review-file.md"
    agent_md.write_text("# stale customization\n")
    _run(project, "init")
    assert agent_md.read_text() != "# stale customization\n"


def test_init_preserves_skill_project_md(project: Path):
    """Project-specific files in skill dirs (e.g., project.md) must NOT
    be overwritten when they already exist."""
    skills_dir = project / ".claude" / "skills" / "sqa-review"
    skills_dir.mkdir(parents=True)
    custom = skills_dir / "project.md"
    custom.write_text("# my customized quality-check command\n")
    _run(project, "init")
    assert custom.read_text() == "# my customized quality-check command\n"


def test_init_preserves_agent_project_files(project: Path):
    """Project-specific agent files (e.g., review-file-prompts.md,
    triage-file-guidelines.md) must NOT be overwritten."""
    agents_dir = project / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    prompts = agents_dir / "review-file-prompts.md"
    guidelines = agents_dir / "triage-file-guidelines.md"
    prompts.write_text("# my customized review prompts\n")
    guidelines.write_text("# my customized triage guidelines\n")
    _run(project, "init")
    assert prompts.read_text() == "# my customized review prompts\n"
    assert guidelines.read_text() == "# my customized triage guidelines\n"


def test_init_creates_missing_project_files(project: Path):
    """When a project file doesn't exist, init creates it from the bundled
    default."""
    _run(project, "init")
    project_md = project / ".claude" / "skills" / "sqa-review" / "project.md"
    assert project_md.is_file()
    # Default content should reference quality-check.
    assert "Quality-check command" in project_md.read_text()


def test_init_is_idempotent_on_re_run(project: Path):
    """Re-running init succeeds: framework gets refreshed, project files
    preserved, .sqa/ left untouched."""
    _run(project, "init")
    # Customize a project file.
    project_md = project / ".claude" / "skills" / "sqa-review" / "project.md"
    project_md.write_text("# user edit\n")
    # Pretend the framework drifted and re-run init.
    skill_md = project / ".claude" / "skills" / "sqa-review" / "SKILL.md"
    skill_md.write_text("# stale\n")
    rc = _run(project, "init")
    assert rc == 0
    # Framework refreshed.
    assert skill_md.read_text() != "# stale\n"
    # Project file preserved.
    assert project_md.read_text() == "# user edit\n"
    # State preserved.
    assert (project / ".sqa" / "config.toml").exists()


def test_init_refuses_non_git(tmp_path: Path, capsys):
    capsys.readouterr()
    rc = _run(tmp_path, "init", expected_exit=1)
    assert rc == 1
    err = capsys.readouterr().err
    assert "git repository" in err


def test_init_refuses_repo_without_commits(tmp_path: Path, capsys):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    capsys.readouterr()
    rc = _run(tmp_path, "init", expected_exit=1)
    assert rc == 1
    err = capsys.readouterr().err
    assert "no commits" in err


def test_record_and_show_finding(initialized: Path, capsys):
    fid = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=Use isinstance instead of type()",
        "--severity=warning",
        "--related=src/sample.py",
    ).strip()
    assert findings.is_valid_id(fid)
    payload = json.loads(_capture(capsys, initialized, "show-finding", fid))
    assert payload["id"] == fid
    assert payload["message"] == "Use isinstance instead of type()"
    assert payload["severity"] == "warning"
    assert payload["status"] == "open"
    assert payload["triage"] is None
    assert payload["related_files"] == ["src/sample.py"]


def test_record_finding_with_anchor_in_sqa_md(initialized: Path, capsys):
    fid = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=Module is overcomplicated",
        "--anchor=src/.sqa.md",
        "--related=src/sample.py",
    ).strip()
    md = (initialized / "src" / ".sqa.md").read_text()
    assert f"sqa: {fid}" in md


def test_record_finding_anchor_uncommentable_fails(initialized: Path):
    (initialized / "data.json").write_text("{}")
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
    a_id = _capture(capsys, initialized, "record-finding", "--message=A", "--severity=info").strip()
    b_id = _capture(capsys, initialized, "record-finding", "--message=B", "--severity=info").strip()
    c_id = _capture(capsys, initialized, "record-finding", "--message=C", "--severity=info").strip()

    _run(initialized, "triage", a_id, "auto", "--rationale=easy fix")
    _run(initialized, "triage", b_id, "ignore", "--rationale=intentional")

    all_findings = json.loads(_capture(capsys, initialized, "list-findings"))
    assert len(all_findings) == 3

    auto = json.loads(_capture(capsys, initialized, "list-findings", "--triage=auto"))
    assert len(auto) == 1
    assert auto[0]["id"] == a_id

    untriaged = json.loads(_capture(capsys, initialized, "list-findings", "--triage=untriaged"))
    assert len(untriaged) == 1
    assert untriaged[0]["id"] == c_id

    assert _capture(capsys, initialized, "list-findings", "--count").strip() == "3"

    limited = json.loads(_capture(capsys, initialized, "list-findings", "--limit=2"))
    assert len(limited) == 2


def test_status(initialized: Path, capsys):
    fid = _capture(
        capsys, initialized, "record-finding", "--message=x", "--severity=warning"
    ).strip()
    _run(initialized, "triage", fid, "auto", "--rationale=easy")

    s = json.loads(_capture(capsys, initialized, "status"))
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
    out = _capture(capsys, initialized, "needs-review").strip().splitlines()
    assert out == ["src/sample.py"]


def test_needs_review_count(initialized: Path, capsys):
    _set_include_globs(initialized, "src/**/*.py")
    assert _capture(capsys, initialized, "needs-review", "--count").strip() == "1"


def test_mark_reviewed_then_needs_review_empty(initialized: Path, capsys):
    _set_include_globs(initialized, "src/**/*.py")
    _run(initialized, "mark-reviewed", "src/sample.py")
    assert _capture(capsys, initialized, "needs-review", "--count").strip() == "0"


def test_needs_review_after_edit(initialized: Path, capsys):
    _set_include_globs(initialized, "src/**/*.py")
    _run(initialized, "mark-reviewed", "src/sample.py")
    # Edit file
    (initialized / "src" / "sample.py").write_text("def hello(): return 'edited'\n")
    assert _capture(capsys, initialized, "needs-review").strip() == "src/sample.py"


def test_resolve_removes_anchor(initialized: Path, capsys):
    sub = subprocess.run
    # Insert an anchor in the source file via record-finding's --anchor flow.
    fid = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=fix me",
        "--anchor=src/sample.py",
    ).strip()
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
    module_id = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=Module-level concern",
        "--anchor=src/.sqa.md",
        "--related=src/sample.py",
    ).strip()
    # Create a file-scope finding directly anchored in src/sample.py.
    file_id = _capture(
        capsys,
        initialized,
        "record-finding",
        "--message=File-level concern",
        "--anchor=src/sample.py",
    ).strip()

    items = json.loads(_capture(capsys, initialized, "findings-for-file", "src/sample.py"))
    ids = {it["id"] for it in items}
    assert module_id in ids
    assert file_id in ids
