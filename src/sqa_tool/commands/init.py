"""sqa-tool init — scaffold .sqa/ and Claude Code skill/agent dirs in the current project."""

import shutil
from pathlib import Path

from sqa_tool import paths
from sqa_tool.config import DEFAULT_CONFIG_TEXT


def _bundled_dir(name: str) -> Path:
    """Locate the bundled `skills/` or `agents/` directory.

    Two layouts are supported:
      - Source checkout: `<repo>/skills/`, `<repo>/agents/` next to `src/`.
      - Wheel install: `sqa_tool/_bundled/skills/`, `sqa_tool/_bundled/agents/`.
    """
    pkg_dir = Path(__file__).resolve().parent.parent  # .../src/sqa_tool/
    # Wheel layout
    wheel_path = pkg_dir / "_bundled" / name
    if wheel_path.is_dir():
        return wheel_path
    # Source layout: walk up two levels (sqa_tool/ → src/ → repo/)
    repo_root = pkg_dir.parent.parent
    src_path = repo_root / name
    if src_path.is_dir():
        return src_path
    raise FileNotFoundError(
        f"Could not locate bundled '{name}/' directory. Tried {wheel_path} and {src_path}."
    )


def _scaffold_claude_dirs(project_root: Path) -> tuple[list[str], list[str]]:
    """Copy bundled skills/agents into project's .claude/ directory.

    Layouts:
      - Skills: each skill is a directory `<name>/SKILL.md`. The whole
        directory is copied as `.claude/skills/<name>/`. If a target
        skill directory already exists, the entire skill is skipped
        (preserves any user customizations within it).
      - Agents: flat `<name>.md` files copied directly. Existing target
        files are skipped.

    Returns (installed_paths, skipped_paths) as project-relative strings.
    """
    installed: list[str] = []
    skipped: list[str] = []

    # Skills: directory-per-skill.
    skills_src = _bundled_dir("skills")
    skills_dst = project_root / ".claude" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    for entry in skills_src.iterdir():
        if not entry.is_dir():
            continue
        target_dir = skills_dst / entry.name
        rel_target = str(target_dir.relative_to(project_root))
        if target_dir.exists():
            skipped.append(rel_target)
            continue
        shutil.copytree(entry, target_dir)
        installed.append(rel_target)

    # Agents: flat .md files.
    agents_src = _bundled_dir("agents")
    agents_dst = project_root / ".claude" / "agents"
    agents_dst.mkdir(parents=True, exist_ok=True)
    for entry in agents_src.iterdir():
        if not (entry.is_file() and entry.suffix == ".md"):
            continue
        target = agents_dst / entry.name
        rel_target = str(target.relative_to(project_root))
        if target.exists():
            skipped.append(rel_target)
            continue
        shutil.copy2(entry, target)
        installed.append(rel_target)

    return installed, skipped


def run(project_root: Path) -> int:
    sqa = paths.sqa_dir(project_root)
    if sqa.exists():
        print(f"error: {sqa} already exists; refusing to overwrite", flush=True)
        return 1

    # Scaffold .claude/ first so a partial failure here doesn't leave .sqa/
    # behind to block subsequent init runs.
    try:
        installed, skipped = _scaffold_claude_dirs(project_root)
    except FileNotFoundError as e:
        print(f"warning: skill/agent scaffolding skipped — {e}", flush=True)
        installed, skipped = [], []

    sqa.mkdir(parents=True)
    paths.findings_dir(project_root).mkdir()
    paths.config_path(project_root).write_text(DEFAULT_CONFIG_TEXT)
    paths.file_status_path(project_root).write_text("{}\n")

    print(f"Initialized {sqa.relative_to(project_root)}/", flush=True)

    if installed:
        print(f"Installed {len(installed)} skill/agent entry(s) under .claude/:", flush=True)
        for p in installed:
            print(f"  {p}", flush=True)
    if skipped:
        print(
            f"Skipped {len(skipped)} pre-existing entry(s) (not overwritten):",
            flush=True,
        )
        for p in skipped:
            print(f"  {p}", flush=True)

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
        "If your project has a quality-check command (./runtools.sh, make check,\n"
        "etc.), edit .claude/skills/sqa-review/SKILL.md and\n"
        ".claude/skills/sqa-resolve/SKILL.md to invoke it where indicated.",
        flush=True,
    )
    return 0
