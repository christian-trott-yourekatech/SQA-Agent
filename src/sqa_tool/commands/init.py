"""sqa-tool init — scaffold .sqa/ and Claude Code skill/agent dirs in the current project."""

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqa_tool import paths
from sqa_tool.config import DEFAULT_CONFIG_TEXT


@dataclass(frozen=True)
class BundledEntry:
    """One bundled file scheduled for installation into `.claude/`."""

    src: Path
    dst: Path
    is_framework: bool


@dataclass
class InstallReport:
    """Project-relative paths affected by `_install_entries`."""

    framework_overwritten: list[str] = field(default_factory=list)
    framework_installed: list[str] = field(default_factory=list)
    project_preserved: list[str] = field(default_factory=list)


# Agents whose primary `<name>.md` file is the framework agent. Any other
# `.md` file in `agents/` (e.g. `review-file-prompts.md`,
# `triage-file-guidelines.md`) is project-specific configuration that the
# framework agent reads at runtime.
_FRAMEWORK_AGENT_STEMS = frozenset({"review-file", "triage-file", "resolve-file", "fix-orphans"})


def _bundled_dir(name: str) -> Path:
    """Locate the bundled `skills/` or `agents/` directory.

    Two layouts are supported:
      - Source checkout: `<repo>/skills/`, `<repo>/agents/` next to `src/`.
      - Wheel install: `sqa_tool/_bundled/skills/`, `sqa_tool/_bundled/agents/`.
    """
    pkg_dir = Path(__file__).resolve().parent.parent  # .../src/sqa_tool/
    wheel_path = pkg_dir / "_bundled" / name
    if wheel_path.is_dir():
        return wheel_path
    repo_root = pkg_dir.parent.parent
    src_path = repo_root / name
    if src_path.is_dir():
        return src_path
    raise FileNotFoundError(
        f"Could not locate bundled '{name}/' directory. Tried {wheel_path} and {src_path}."
    )


def _is_framework_skill_file(name: str) -> bool:
    """Inside a bundled skill directory, only `SKILL.md` is framework."""
    return name == "SKILL.md"


def _is_framework_agent_file(stem: str) -> bool:
    """Inside `agents/`, framework agents are the named ones; anything else
    (e.g. `review-file-prompts.md`) is project-specific."""
    return stem in _FRAMEWORK_AGENT_STEMS


def _bundled_claude_entries(project_root: Path) -> list[BundledEntry]:
    """Yield a `BundledEntry` for every bundled skill/agent file.

    Framework files are overwritten by `init`; project-specific files are
    preserved when they already exist (created when they don't).

    For skills: walks the top level of `skills/<name>/` (one level — nested
    files are not picked up). `SKILL.md` is framework; everything else
    (e.g. `project.md`) is project-specific.

    For agents: walks `agents/` for `.md` files. Files whose stem is in
    `_FRAMEWORK_AGENT_STEMS` are framework; the rest (`-prompts`,
    `-guidelines`, etc.) are project-specific.
    """
    entries: list[BundledEntry] = []

    skills_src = _bundled_dir("skills")
    skills_dst_root = project_root / ".claude" / "skills"
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir():
            continue
        for src_file in sorted(skill_dir.iterdir()):
            if not (src_file.is_file() and src_file.suffix == ".md"):
                continue
            dst_file = skills_dst_root / skill_dir.name / src_file.name
            entries.append(
                BundledEntry(src_file, dst_file, _is_framework_skill_file(src_file.name))
            )

    agents_src = _bundled_dir("agents")
    agents_dst_root = project_root / ".claude" / "agents"
    for src_file in sorted(agents_src.iterdir()):
        if not (src_file.is_file() and src_file.suffix == ".md"):
            continue
        dst_file = agents_dst_root / src_file.name
        entries.append(BundledEntry(src_file, dst_file, _is_framework_agent_file(src_file.stem)))

    return entries


def _install_entries(project_root: Path, entries: list[BundledEntry]) -> InstallReport:
    """Copy bundled entries into `.claude/`, applying the framework/project
    overwrite policy.

    Framework files: always written (overwriting any existing copy). Project
    files: written only if the target doesn't exist.

    The returned `InstallReport` carries project-relative paths:
      - framework_overwritten: framework files that replaced an existing copy.
      - framework_installed: framework files that didn't have a prior copy.
      - project_preserved: project files left in place because the user has
        a customized version. Project files that didn't exist are silently
        installed (caller doesn't usually need to know).
    """
    report = InstallReport()

    for entry in entries:
        entry.dst.parent.mkdir(parents=True, exist_ok=True)
        rel = str(entry.dst.relative_to(project_root))
        if entry.is_framework:
            existed = entry.dst.exists()
            shutil.copy2(entry.src, entry.dst)
            (report.framework_overwritten if existed else report.framework_installed).append(rel)
        else:
            if entry.dst.exists():
                report.project_preserved.append(rel)
                continue
            shutil.copy2(entry.src, entry.dst)

    return report


def run(project_root: Path) -> int:
    sqa = paths.sqa_dir(project_root)
    sqa_existed = sqa.exists()

    if not sqa_existed:
        sqa.mkdir(parents=True)
        paths.findings_dir(project_root).mkdir()
        paths.config_path(project_root).write_text(DEFAULT_CONFIG_TEXT)
        paths.file_status_path(project_root).write_text("{}\n")
        print(f"Initialized {sqa.relative_to(project_root)}/", flush=True)
    else:
        print(
            f"{sqa.relative_to(project_root)}/ already exists; preserving project state. "
            "Refreshing skill/agent framework files only.",
            flush=True,
        )

    try:
        entries = _bundled_claude_entries(project_root)
    except FileNotFoundError as e:
        print(f"warning: skill/agent scaffolding skipped — {e}", file=sys.stderr, flush=True)
        entries = []

    report = _install_entries(project_root, entries)

    if report.framework_installed:
        print(
            f"\nInstalled {len(report.framework_installed)} framework file(s):",
            flush=True,
        )
        for p in report.framework_installed:
            print(f"  {p}", flush=True)

    if report.framework_overwritten:
        print(
            f"\nUpdated {len(report.framework_overwritten)} framework file(s) "
            "(overwritten with bundled defaults):",
            flush=True,
        )
        for p in report.framework_overwritten:
            print(f"  {p}", flush=True)

    if report.project_preserved:
        print(
            f"\nPreserved {len(report.project_preserved)} project-specific file(s) "
            "(not overwritten):",
            flush=True,
        )
        for p in report.project_preserved:
            print(f"  {p}", flush=True)

    if not sqa_existed:
        print("", flush=True)
        print(
            "Note: by default, .sqa/findings/ will be tracked by git, preserving the\n"
            "audit trail of every finding. For security-sensitive projects (or repos\n"
            "shared with parties who shouldn't see vulnerability descriptions), you\n"
            "may want to add `.sqa/findings/` to your .gitignore. The trade-off is\n"
            "loss of git-based history and merge-friendly storage.",
            flush=True,
        )
    print("", flush=True)
    print(
        "Project-specific configuration (quality-check command, review prompts,\n"
        "triage guidelines) lives in:\n"
        "  .claude/skills/sqa-review/project.md\n"
        "  .claude/skills/sqa-resolve/project.md\n"
        "  .claude/agents/review-file-prompts.md\n"
        "  .claude/agents/triage-file-guidelines.md\n"
        "Edit those to tailor the system to your project. They are preserved\n"
        "across `sqa-tool init` upgrades; the framework files (SKILL.md,\n"
        "<agent>.md) are overwritten so you get the latest workflow logic.",
        flush=True,
    )
    return 0
