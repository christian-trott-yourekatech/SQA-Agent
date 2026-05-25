"""Integration tests for init, needs-review, and mark-reviewed CLI commands."""

import subprocess
from pathlib import Path

import pytest
from conftest import capture_cli, run_cli


def _drain(capsys):
    """Discard captured output so the next readouterr() returns only new output.

    Sprinkled through tests that perform a setup `run_cli` (whose stdout/stderr
    we don't care about) followed by an act `run_cli` whose output we want to
    assert on.
    """
    capsys.readouterr()


def test_framework_agent_stems_covers_all_framework_files():
    """Every bundled `agents/*.md` must be classifiable: either its stem is in
    `_FRAMEWORK_AGENT_STEMS`, or its stem ends in a project-file suffix
    (`-prompts`, `-guidelines`). A new framework agent added without updating
    the set would silently be treated as project-specific — preserved across
    `sqa-tool init` upgrades and never refreshed. This test makes that loud.
    """
    from sqa_tool.commands.init import (
        _FRAMEWORK_AGENT_STEMS,
        _PROJECT_AGENT_SUFFIXES,
        _bundled_dir,
    )

    agents_dir = _bundled_dir("agents")
    unclassified = []
    for f in sorted(agents_dir.iterdir()):
        if not (f.is_file() and f.suffix == ".md"):
            continue
        stem = f.stem
        if stem.endswith(_PROJECT_AGENT_SUFFIXES):
            continue
        if stem not in _FRAMEWORK_AGENT_STEMS:
            unclassified.append(f.name)
    assert not unclassified, (
        f"Bundled agent file(s) {unclassified} are neither in "
        f"_FRAMEWORK_AGENT_STEMS nor end in {_PROJECT_AGENT_SUFFIXES}. "
        "Add the stem to the set, or rename to a project-file suffix."
    )


def test_init(project: Path, monkeypatch):
    run_cli(monkeypatch, project, "init")
    assert (project / ".sqa" / "config.toml").exists()
    assert (project / ".sqa" / "file_status.json").exists()
    assert not (project / ".sqa" / "findings").exists()


def test_init_scaffolds_skills_and_agents(project: Path, monkeypatch):
    run_cli(monkeypatch, project, "init")
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
    assert (agents_dir / "triage-general.md").is_file()
    assert (agents_dir / "resolve-general.md").is_file()
    assert not (agents_dir / "fix-orphans.md").exists()
    # Subagent project files (flat .md, preserved across upgrades).
    assert (agents_dir / "review-file-prompt.md").is_file()
    assert (agents_dir / "triage-guidelines.md").is_file()


def test_init_overwrites_framework_skill_md(project: Path, monkeypatch):
    """Framework SKILL.md must be overwritten on re-init so users get the
    latest workflow logic."""
    from sqa_tool.commands.init import _bundled_dir

    skills_dir = project / ".claude" / "skills" / "sqa-review"
    skills_dir.mkdir(parents=True)
    skill_md = skills_dir / "SKILL.md"
    skill_md.write_text("# stale customization\n")
    run_cli(monkeypatch, project, "init")
    # Stale content is replaced by the bundled framework. Byte-compare
    # against the bundled source rather than soft-checking for a marker
    # word: this catches regressions where overwrite happens but writes
    # the wrong bytes, and doesn't break if bundled wording shifts.
    bundled = (_bundled_dir("skills") / "sqa-review" / "SKILL.md").read_bytes()
    assert skill_md.read_bytes() == bundled


def test_init_overwrites_framework_agent_md(project: Path, monkeypatch):
    """Framework agent <name>.md must be overwritten on re-init."""
    from sqa_tool.commands.init import _bundled_dir

    agents_dir = project / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    agent_md = agents_dir / "review-file.md"
    agent_md.write_text("# stale customization\n")
    run_cli(monkeypatch, project, "init")
    # Byte-compare against the bundled source (see sibling SKILL.md test
    # for rationale).
    bundled = (_bundled_dir("agents") / "review-file.md").read_bytes()
    assert agent_md.read_bytes() == bundled


def test_init_preserves_skill_project_md(project: Path, monkeypatch):
    """Project-specific files in skill dirs (e.g., project.md) must NOT
    be overwritten when they already exist."""
    skills_dir = project / ".claude" / "skills" / "sqa-review"
    skills_dir.mkdir(parents=True)
    custom = skills_dir / "project.md"
    custom.write_text("# my customized quality-check command\n")
    run_cli(monkeypatch, project, "init")
    assert custom.read_text() == "# my customized quality-check command\n"


def test_init_preserves_agent_project_files(project: Path, monkeypatch):
    """Project-specific agent files (e.g., review-file-prompt.md,
    triage-guidelines.md) must NOT be overwritten."""
    agents_dir = project / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    prompt = agents_dir / "review-file-prompt.md"
    guidelines = agents_dir / "triage-guidelines.md"
    prompt.write_text("# my customized review prompt\n")
    guidelines.write_text("# my customized triage guidelines\n")
    run_cli(monkeypatch, project, "init")
    assert prompt.read_text() == "# my customized review prompt\n"
    assert guidelines.read_text() == "# my customized triage guidelines\n"


def test_init_creates_missing_project_files(project: Path, monkeypatch):
    """When a project file doesn't exist, init creates it from the bundled
    default."""
    run_cli(monkeypatch, project, "init")
    project_md = project / ".claude" / "skills" / "sqa-review" / "project.md"
    assert project_md.is_file()
    # Default content should reference quality-check.
    assert "Quality-check command" in project_md.read_text()


def test_init_is_idempotent_on_re_run(project: Path, monkeypatch):
    """Re-running init succeeds: framework gets refreshed, project files
    preserved, .sqa/ left untouched."""
    run_cli(monkeypatch, project, "init")
    # Customize a project file.
    project_md = project / ".claude" / "skills" / "sqa-review" / "project.md"
    project_md.write_text("# user edit\n")
    # Pretend the framework drifted and re-run init.
    skill_md = project / ".claude" / "skills" / "sqa-review" / "SKILL.md"
    skill_md.write_text("# stale\n")
    rc = run_cli(monkeypatch, project, "init")
    assert rc == 0
    # Framework refreshed.
    assert skill_md.read_text() != "# stale\n"
    # Project file preserved.
    assert project_md.read_text() == "# user edit\n"
    # State preserved.
    assert (project / ".sqa" / "config.toml").exists()


# ---- Install-report categorization (findings #9, #10) --------------------
#
# These tests pin down the InstallReport buckets across the four scenarios
# init can be in on any given run. They assert on the stdout output that
# the print helpers produce, since that's the contract the user sees.

# Substrings the install report uses to introduce each bucket. Tests assert
# on these as a stable contract over the exact wording (which can change
# without invalidating the scenario shape).
_INSTALLED_FRAMEWORK_BANNER = "framework file(s):"
_UPDATED_FRAMEWORK_BANNER = "Updated"
_UNCHANGED_FRAMEWORK_BANNER = "Framework already current"
_INSTALLED_PROJECT_BANNER = "project-specific file(s) (defaults"
_PRESERVED_PROJECT_BANNER = "Preserved"
_EDIT_TO_TAILOR = "Edit those to tailor"


def test_init_fresh_install_categorizes_everything_as_new(project: Path, monkeypatch, capsys):
    """On fresh init, all bundled framework files are 'installed' (not
    'updated' — they didn't exist before), all project defaults are
    'installed', and nothing is preserved or unchanged."""
    run_cli(monkeypatch, project, "init")
    out = capsys.readouterr().out

    assert _INSTALLED_FRAMEWORK_BANNER in out
    assert _INSTALLED_PROJECT_BANNER in out
    assert _EDIT_TO_TAILOR in out  # fresh init → "edit to tailor" fires
    # Nothing should be reported as updated, unchanged, or preserved on
    # a truly fresh install.
    assert _UPDATED_FRAMEWORK_BANNER not in out
    assert _UNCHANGED_FRAMEWORK_BANNER not in out
    assert _PRESERVED_PROJECT_BANNER not in out


def test_init_noop_rerun_reports_unchanged_only(project: Path, monkeypatch, capsys):
    """A re-run with no source/destination drift reports framework files
    as unchanged (summary line only, no per-file enumeration) and project
    files as preserved. The 'edit to tailor' section is omitted because
    no new project defaults were installed."""
    run_cli(monkeypatch, project, "init")
    _drain(capsys)

    rc = run_cli(monkeypatch, project, "init")
    assert rc == 0
    out = capsys.readouterr().out

    assert _UNCHANGED_FRAMEWORK_BANNER in out
    assert _PRESERVED_PROJECT_BANNER in out
    # No-op re-run: no installs and no updates.
    assert _INSTALLED_FRAMEWORK_BANNER not in out
    assert _UPDATED_FRAMEWORK_BANNER not in out
    assert _INSTALLED_PROJECT_BANNER not in out
    # And, critically: no "edit to tailor" directive when nothing new
    # was installed.
    assert _EDIT_TO_TAILOR not in out


def test_init_with_stale_framework_reports_updated(project: Path, monkeypatch, capsys):
    """When one framework file's content differs from the bundled
    version, it appears in 'updated' and only it. The other framework
    files report as unchanged."""
    run_cli(monkeypatch, project, "init")
    _drain(capsys)
    # Make exactly one framework file differ from bundled.
    skill_md = project / ".claude" / "skills" / "sqa-review" / "SKILL.md"
    skill_md.write_text("# stale\n")

    run_cli(monkeypatch, project, "init")
    out = capsys.readouterr().out

    assert _UPDATED_FRAMEWORK_BANNER in out
    assert _UNCHANGED_FRAMEWORK_BANNER in out  # the other framework files
    # Pin SKILL.md to the 'Updated' bucket, not 'unchanged'. A regression
    # that listed it under unchanged would still mention the path somewhere
    # in `out`, so a bare `in out` check wouldn't catch the swap.
    updated_idx = out.index(_UPDATED_FRAMEWORK_BANNER)
    unchanged_idx = out.index(_UNCHANGED_FRAMEWORK_BANNER)
    assert updated_idx < unchanged_idx, (
        "expected 'Updated' bucket to be printed before 'Framework already current'"
    )
    updated_section = out[updated_idx:unchanged_idx]
    unchanged_section = out[unchanged_idx:]
    assert ".claude/skills/sqa-review/SKILL.md" in updated_section
    assert ".claude/skills/sqa-review/SKILL.md" not in unchanged_section
    # No new project files installed → no "edit to tailor" directive.
    assert _EDIT_TO_TAILOR not in out


def test_init_with_missing_project_file_reports_project_installed(
    project: Path, monkeypatch, capsys
):
    """When a project file is missing on a re-run (e.g. user deleted it,
    or a tool upgrade added a new project default), it appears in
    'project_installed' and triggers the 'edit to tailor' directive
    for just that file."""
    run_cli(monkeypatch, project, "init")
    _drain(capsys)
    # Delete one project file so the next init re-installs it.
    project_md = project / ".claude" / "skills" / "sqa-review" / "project.md"
    project_md.unlink()

    run_cli(monkeypatch, project, "init")
    out = capsys.readouterr().out

    from sqa_tool.commands.init import _NEW_PROJECT_FILES_HEADER

    assert _INSTALLED_PROJECT_BANNER in out
    assert ".claude/skills/sqa-review/project.md" in out
    # The directive fires because a new project file was installed —
    # but with the upgrade-framing header, not the fresh-init framing.
    assert _EDIT_TO_TAILOR in out
    assert _NEW_PROJECT_FILES_HEADER in out
    # Other project files still preserved.
    assert _PRESERVED_PROJECT_BANNER in out


def test_install_report_no_op_makes_no_filesystem_writes(project: Path, monkeypatch, capsys):
    """A no-op re-run must not bump mtimes on framework files. The
    byte-compare check in _install_entries skips the copy entirely when
    content is identical; if it didn't, every re-run would silently
    re-touch every framework file."""
    from sqa_tool.commands.init import _bundled_claude_entries

    run_cli(monkeypatch, project, "init")
    _drain(capsys)
    # Cover the full set of bundled framework files, not a hand-picked pair.
    # A future bug that re-touched only agent files (or only skill files)
    # would slip past a spot-check; iterating the canonical enumeration keeps
    # the assertion in sync as new framework files land in the bundle.
    framework_files = [
        entry.dst for entry in _bundled_claude_entries(project) if entry.is_framework
    ]
    assert framework_files, "expected at least one bundled framework entry"
    mtimes_before = {f: f.stat().st_mtime_ns for f in framework_files}

    run_cli(monkeypatch, project, "init")

    for f in framework_files:
        assert f.stat().st_mtime_ns == mtimes_before[f], (
            f"no-op re-init re-touched {f.relative_to(project)} — byte-compare "
            "in _install_entries isn't skipping the copy as it should"
        )


def _seed_legacy_findings_dir(project: Path) -> Path:
    findings_dir = project / ".sqa" / "findings"
    findings_dir.mkdir(parents=True)
    # Seed an inner file too, but return the directory itself: the warning
    # names the directory, and the documented invariant is that init leaves
    # the directory in place (not just its contents).
    (findings_dir / "ABCDE.json").write_text("{}")
    return findings_dir


def _seed_legacy_sqa_md(project: Path) -> Path:
    seeded = project / ".sqa.md"
    seeded.write_text("<!-- sqa: ABCDE -->\n")
    return seeded


def _seed_legacy_fix_orphans(project: Path) -> Path:
    seeded = project / ".claude" / "agents" / "fix-orphans.md"
    seeded.write_text("# legacy\n")
    return seeded


@pytest.mark.parametrize(
    ("seed", "expected_substring", "other_substrings"),
    [
        (_seed_legacy_findings_dir, ".sqa/findings", (".sqa.md", "fix-orphans.md")),
        (_seed_legacy_sqa_md, ".sqa.md", (".sqa/findings", "fix-orphans.md")),
        (_seed_legacy_fix_orphans, "fix-orphans.md", (".sqa/findings", ".sqa.md")),
    ],
    ids=["findings_dir", "sqa_md", "fix_orphans"],
)
def test_init_warns_on_legacy_state(
    project: Path, monkeypatch, capsys, seed, expected_substring, other_substrings
):
    """If init finds a leftover legacy artifact (a `.sqa/findings/` directory,
    a `.sqa.md` file, or an old agent filename), it warns and leaves the file
    in place. Each artifact is verified in isolation: the warning names it and
    *only* it, and the file isn't deleted."""
    # Bootstrap a clean .sqa/, then seed just one legacy artifact alongside.
    run_cli(monkeypatch, project, "init")
    _drain(capsys)
    seeded_path = seed(project)

    run_cli(monkeypatch, project, "init")
    out = capsys.readouterr().out

    assert "earlier version of this tool" in out
    assert expected_substring in out
    for other in other_substrings:
        assert other not in out, f"warning mentioned un-seeded artifact {other!r}"
    assert seeded_path.exists(), "init must not delete legacy artifacts"


def test_init_no_legacy_warning_on_clean_project(project: Path, monkeypatch, capsys):
    """A fresh init in a clean project doesn't emit the legacy warning."""
    run_cli(monkeypatch, project, "init")
    out = capsys.readouterr().out
    assert "earlier version of this tool" not in out


def test_init_refuses_non_git(tmp_path: Path, capsys, monkeypatch):
    rc = run_cli(monkeypatch, tmp_path, "init", expected_exit=1)
    assert rc == 1
    err = capsys.readouterr().err
    assert "git repository" in err


def test_init_refuses_repo_without_commits(tmp_path: Path, capsys, monkeypatch):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    rc = run_cli(monkeypatch, tmp_path, "init", expected_exit=1)
    assert rc == 1
    err = capsys.readouterr().err
    assert "no commits" in err


@pytest.mark.parametrize("cmd", ["list-findings", "needs-review"])
def test_negative_limit_rejected(cmd, initialized: Path, monkeypatch):
    # argparse should reject --limit=-1 rather than silently end-slicing the
    # result list. Call cli_main directly because argparse exits before
    # run_cli can assert on the return code.
    from sqa_tool.cli import main as cli_main

    monkeypatch.chdir(initialized)
    with pytest.raises(SystemExit) as excinfo:
        cli_main([cmd, "--limit=-1"])
    assert excinfo.value.code == 2


def test_needs_review_initial_lists_all(configured: Path, capsys, monkeypatch):
    out = capture_cli(capsys, monkeypatch, configured, "needs-review").strip().splitlines()
    assert out == ["src/sample.py"]


def test_needs_review_count(configured: Path, capsys, monkeypatch):
    assert capture_cli(capsys, monkeypatch, configured, "needs-review", "--count").strip() == "1"


def test_mark_reviewed_then_needs_review_empty(configured: Path, capsys, monkeypatch):
    run_cli(monkeypatch, configured, "mark-reviewed", "src/sample.py")
    assert capture_cli(capsys, monkeypatch, configured, "needs-review", "--count").strip() == "0"


def test_needs_review_after_edit(configured: Path, capsys, monkeypatch):
    run_cli(monkeypatch, configured, "mark-reviewed", "src/sample.py")
    # needs-review hashes the working tree, not HEAD — no commit needed after the edit.
    (configured / "src" / "sample.py").write_text("def hello(): return 'edited'\n")
    assert capture_cli(capsys, monkeypatch, configured, "needs-review").strip() == "src/sample.py"
