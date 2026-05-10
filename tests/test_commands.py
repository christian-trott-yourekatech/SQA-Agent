"""Integration tests: run CLI subcommands against a real temp project."""

import json
import subprocess
from pathlib import Path

from conftest import _capture, _commit, _run

from sqa_tool import findings


def test_framework_agent_stems_covers_all_framework_files():
    """Every bundled `agents/*.md` must be classifiable: either its stem is in
    `_FRAMEWORK_AGENT_STEMS`, or its stem ends in a project-file suffix
    (`-prompts`, `-guidelines`). A new framework agent added without updating
    the set would silently be treated as project-specific — preserved across
    `sqa-tool init` upgrades and never refreshed. This test makes that loud.
    """
    from sqa_tool.commands.init import _FRAMEWORK_AGENT_STEMS, _bundled_dir

    agents_dir = _bundled_dir("agents")
    project_suffixes = ("-prompts", "-guidelines")
    unclassified = []
    for f in sorted(agents_dir.iterdir()):
        if not (f.is_file() and f.suffix == ".md"):
            continue
        stem = f.stem
        if stem.endswith(project_suffixes):
            continue
        if stem not in _FRAMEWORK_AGENT_STEMS:
            unclassified.append(f.name)
    assert not unclassified, (
        f"Bundled agent file(s) {unclassified} are neither in "
        f"_FRAMEWORK_AGENT_STEMS nor end in {project_suffixes}. "
        "Add the stem to the set, or rename to a project-file suffix."
    )


def test_init(project: Path, monkeypatch):
    _run(monkeypatch, project, "init")
    assert (project / ".sqa" / "config.toml").exists()
    assert (project / ".sqa" / "findings").is_dir()
    assert (project / ".sqa" / "file_status.json").exists()


def test_init_scaffolds_skills_and_agents(project: Path, monkeypatch):
    _run(monkeypatch, project, "init")
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


def test_init_overwrites_framework_skill_md(project: Path, monkeypatch):
    """Framework SKILL.md must be overwritten on re-init so users get the
    latest workflow logic."""
    skills_dir = project / ".claude" / "skills" / "sqa-review"
    skills_dir.mkdir(parents=True)
    skill_md = skills_dir / "SKILL.md"
    skill_md.write_text("# stale customization\n")
    _run(monkeypatch, project, "init")
    # Stale content is replaced by the bundled framework.
    assert skill_md.read_text() != "# stale customization\n"
    assert "framework" in skill_md.read_text().lower()


def test_init_overwrites_framework_agent_md(project: Path, monkeypatch):
    """Framework agent <name>.md must be overwritten on re-init."""
    agents_dir = project / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    agent_md = agents_dir / "review-file.md"
    agent_md.write_text("# stale customization\n")
    _run(monkeypatch, project, "init")
    assert agent_md.read_text() != "# stale customization\n"


def test_init_preserves_skill_project_md(project: Path, monkeypatch):
    """Project-specific files in skill dirs (e.g., project.md) must NOT
    be overwritten when they already exist."""
    skills_dir = project / ".claude" / "skills" / "sqa-review"
    skills_dir.mkdir(parents=True)
    custom = skills_dir / "project.md"
    custom.write_text("# my customized quality-check command\n")
    _run(monkeypatch, project, "init")
    assert custom.read_text() == "# my customized quality-check command\n"


def test_init_preserves_agent_project_files(project: Path, monkeypatch):
    """Project-specific agent files (e.g., review-file-prompts.md,
    triage-file-guidelines.md) must NOT be overwritten."""
    agents_dir = project / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    prompts = agents_dir / "review-file-prompts.md"
    guidelines = agents_dir / "triage-file-guidelines.md"
    prompts.write_text("# my customized review prompts\n")
    guidelines.write_text("# my customized triage guidelines\n")
    _run(monkeypatch, project, "init")
    assert prompts.read_text() == "# my customized review prompts\n"
    assert guidelines.read_text() == "# my customized triage guidelines\n"


def test_init_creates_missing_project_files(project: Path, monkeypatch):
    """When a project file doesn't exist, init creates it from the bundled
    default."""
    _run(monkeypatch, project, "init")
    project_md = project / ".claude" / "skills" / "sqa-review" / "project.md"
    assert project_md.is_file()
    # Default content should reference quality-check.
    assert "Quality-check command" in project_md.read_text()


def test_init_is_idempotent_on_re_run(project: Path, monkeypatch):
    """Re-running init succeeds: framework gets refreshed, project files
    preserved, .sqa/ left untouched."""
    _run(monkeypatch, project, "init")
    # Customize a project file.
    project_md = project / ".claude" / "skills" / "sqa-review" / "project.md"
    project_md.write_text("# user edit\n")
    # Pretend the framework drifted and re-run init.
    skill_md = project / ".claude" / "skills" / "sqa-review" / "SKILL.md"
    skill_md.write_text("# stale\n")
    rc = _run(monkeypatch, project, "init")
    assert rc == 0
    # Framework refreshed.
    assert skill_md.read_text() != "# stale\n"
    # Project file preserved.
    assert project_md.read_text() == "# user edit\n"
    # State preserved.
    assert (project / ".sqa" / "config.toml").exists()


def test_init_refuses_non_git(tmp_path: Path, capsys, monkeypatch):
    capsys.readouterr()
    rc = _run(monkeypatch, tmp_path, "init", expected_exit=1)
    assert rc == 1
    err = capsys.readouterr().err
    assert "git repository" in err


def test_init_refuses_repo_without_commits(tmp_path: Path, capsys, monkeypatch):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    capsys.readouterr()
    rc = _run(monkeypatch, tmp_path, "init", expected_exit=1)
    assert rc == 1
    err = capsys.readouterr().err
    assert "no commits" in err


def test_record_and_show_finding(initialized: Path, capsys, monkeypatch):
    fid = _capture(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=Use isinstance instead of type()",
        "--severity=warning",
        "--related=src/sample.py",
    ).strip()
    assert findings.is_valid_id(fid)
    payload = json.loads(_capture(capsys, monkeypatch, initialized, "show-finding", fid))
    assert payload["id"] == fid
    assert payload["message"] == "Use isinstance instead of type()"
    assert payload["severity"] == "warning"
    assert payload["status"] == "open"
    assert payload["triage"] is None
    assert payload["related_files"] == ["src/sample.py"]


def test_record_finding_with_anchor_in_sqa_md(initialized: Path, capsys, monkeypatch):
    fid = _capture(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=Module is overcomplicated",
        "--anchor=src/.sqa.md",
        "--related=src/sample.py",
    ).strip()
    md = (initialized / "src" / ".sqa.md").read_text()
    assert f"sqa: {fid}" in md


def test_record_finding_anchor_uncommentable_fails(initialized: Path, capsys, monkeypatch):
    (initialized / "data.json").write_text("{}")
    capsys.readouterr()
    rc = _run(
        monkeypatch,
        initialized,
        "record-finding",
        "--message=bad",
        "--anchor=data.json",
        expected_exit=1,
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "not commentable" in (captured.err + captured.out)
    # No leftover finding should remain.
    fdir = initialized / ".sqa" / "findings"
    assert list(fdir.iterdir()) == []


def test_list_findings_filters(initialized: Path, capsys, monkeypatch):
    # Record three findings with different triage states.
    a_id = _capture(
        capsys, monkeypatch, initialized, "record-finding", "--message=A", "--severity=info"
    ).strip()
    b_id = _capture(
        capsys, monkeypatch, initialized, "record-finding", "--message=B", "--severity=info"
    ).strip()
    c_id = _capture(
        capsys, monkeypatch, initialized, "record-finding", "--message=C", "--severity=info"
    ).strip()

    _run(monkeypatch, initialized, "triage", a_id, "auto", "--rationale=easy fix")
    _run(monkeypatch, initialized, "triage", b_id, "ignore", "--rationale=intentional")

    all_findings = json.loads(_capture(capsys, monkeypatch, initialized, "list-findings"))
    assert len(all_findings) == 3

    auto = json.loads(_capture(capsys, monkeypatch, initialized, "list-findings", "--triage=auto"))
    assert len(auto) == 1
    assert auto[0]["id"] == a_id

    untriaged = json.loads(
        _capture(capsys, monkeypatch, initialized, "list-findings", "--triage=untriaged")
    )
    assert len(untriaged) == 1
    assert untriaged[0]["id"] == c_id

    assert _capture(capsys, monkeypatch, initialized, "list-findings", "--count").strip() == "3"

    limited = json.loads(_capture(capsys, monkeypatch, initialized, "list-findings", "--limit=2"))
    assert len(limited) == 2


def test_negative_limit_rejected(initialized: Path, capsys, monkeypatch):
    # argparse should reject --limit=-1 (and its needs-review equivalent)
    # rather than silently end-slicing the result list.
    import pytest

    with pytest.raises(SystemExit):
        _run(monkeypatch, initialized, "list-findings", "--limit=-1")
    with pytest.raises(SystemExit):
        _run(monkeypatch, initialized, "needs-review", "--limit=-1")


def test_status(initialized: Path, capsys, monkeypatch):
    fid = _capture(
        capsys, monkeypatch, initialized, "record-finding", "--message=x", "--severity=warning"
    ).strip()
    _run(monkeypatch, initialized, "triage", fid, "auto", "--rationale=easy")

    s = json.loads(_capture(capsys, monkeypatch, initialized, "status"))
    assert s["total"] == 1
    assert s["by_triage"]["auto"] == 1
    assert s["by_severity"]["warning"] == 1
    assert s["by_status"]["open"] == 1


def _set_include_globs(project: Path, *patterns: str) -> None:
    cfg = project / ".sqa" / "config.toml"
    text = cfg.read_text()
    new = []
    replaced = False
    for line in text.splitlines():
        if line.strip().startswith("include ="):
            new.append("include = [" + ", ".join(f'"{p}"' for p in patterns) + "]")
            replaced = True
        else:
            new.append(line)
    assert replaced, f"no 'include =' line found in {cfg}"
    cfg.write_text("\n".join(new) + "\n")


def test_needs_review_initial_lists_all(initialized: Path, capsys, monkeypatch):
    _set_include_globs(initialized, "src/**/*.py")
    out = _capture(capsys, monkeypatch, initialized, "needs-review").strip().splitlines()
    assert out == ["src/sample.py"]


def test_needs_review_count(initialized: Path, capsys, monkeypatch):
    _set_include_globs(initialized, "src/**/*.py")
    assert _capture(capsys, monkeypatch, initialized, "needs-review", "--count").strip() == "1"


def test_mark_reviewed_then_needs_review_empty(initialized: Path, capsys, monkeypatch):
    _set_include_globs(initialized, "src/**/*.py")
    _run(monkeypatch, initialized, "mark-reviewed", "src/sample.py")
    assert _capture(capsys, monkeypatch, initialized, "needs-review", "--count").strip() == "0"


def test_needs_review_after_edit(initialized: Path, capsys, monkeypatch):
    _set_include_globs(initialized, "src/**/*.py")
    _run(monkeypatch, initialized, "mark-reviewed", "src/sample.py")
    # Edit file
    (initialized / "src" / "sample.py").write_text("def hello(): return 'edited'\n")
    assert _capture(capsys, monkeypatch, initialized, "needs-review").strip() == "src/sample.py"


def test_resolve_removes_anchor(initialized: Path, capsys, monkeypatch):
    # Insert an anchor in the source file via record-finding's --anchor flow.
    fid = _capture(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=fix me",
        "--anchor=src/sample.py",
    ).strip()
    assert f"sqa: {fid}" in (initialized / "src" / "sample.py").read_text()
    # Commit so git tracks the anchor.
    _commit(initialized, "anchor")
    _run(monkeypatch, initialized, "resolve", fid, "--rationale=fixed it")
    assert f"sqa: {fid}" not in (initialized / "src" / "sample.py").read_text()


def test_findings_for_file_includes_ancestor_scope(initialized: Path, capsys, monkeypatch):
    # Create a module-scope (ancestor) finding anchored in src/.sqa.md with related src/sample.py.
    module_id = _capture(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=Module-level concern",
        "--anchor=src/.sqa.md",
        "--related=src/sample.py",
    ).strip()
    # Create a file-scope finding directly anchored in src/sample.py.
    file_id = _capture(
        capsys,
        monkeypatch,
        initialized,
        "record-finding",
        "--message=File-level concern",
        "--anchor=src/sample.py",
    ).strip()

    items = json.loads(
        _capture(capsys, monkeypatch, initialized, "findings-for-file", "src/sample.py")
    )
    ids = {it["id"] for it in items}
    assert module_id in ids
    assert file_id in ids
