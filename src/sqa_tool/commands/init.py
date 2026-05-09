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


def _bundled_claude_entries(
    project_root: Path,
) -> list[tuple[Path, Path, str]]:
    """Yield (src, dst, kind) for every bundled skill or agent.

    Single source of truth for the bundled-layout filter rules: skills are
    directories under `skills/`, agents are `.md` files under `agents/`.
    Used by both the pre-flight conflict check and the actual copy phase
    so they can't drift apart when the layout changes.
    """
    entries: list[tuple[Path, Path, str]] = []
    skills_src = _bundled_dir("skills")
    skills_dst = project_root / ".claude" / "skills"
    for entry in skills_src.iterdir():
        if entry.is_dir():
            entries.append((entry, skills_dst / entry.name, "skill"))
    agents_src = _bundled_dir("agents")
    agents_dst = project_root / ".claude" / "agents"
    for entry in agents_src.iterdir():
        if entry.is_file() and entry.suffix == ".md":
            entries.append((entry, agents_dst / entry.name, "agent"))
    return entries


def _planned_claude_targets(project_root: Path) -> list[Path]:
    """Return the absolute target paths `_scaffold_claude_dirs` would create.

    Used by the pre-flight conflict check in `run()` so existing entries
    abort the whole init rather than getting silently skipped.
    """
    return [dst for _src, dst, _kind in _bundled_claude_entries(project_root)]


def _scaffold_claude_dirs(project_root: Path) -> list[str]:
    """Copy bundled skills/agents into project's .claude/ directory.

    Layouts:
      - Skills: each skill is a directory `<name>/SKILL.md`. The whole
        directory is copied as `.claude/skills/<name>/`.
      - Agents: flat `<name>.md` files copied directly.

    Caller is responsible for ensuring no targets pre-exist (see
    `_planned_claude_targets` and the conflict check in `run()`).

    Returns project-relative paths of installed entries.
    """
    installed: list[str] = []
    for src, dst, kind in _bundled_claude_entries(project_root):
        dst.parent.mkdir(parents=True, exist_ok=True)
        if kind == "skill":
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        installed.append(str(dst.relative_to(project_root)))
    return installed


def run(project_root: Path) -> int:
    sqa = paths.sqa_dir(project_root)
    if sqa.exists():
        print(f"error: {sqa} already exists; refusing to overwrite", flush=True)
        return 1

    # Pre-flight: refuse if any planned skill/agent target already exists.
    # All-or-nothing: silent skipping leads to confusing partial state
    # (some bundled, some user-customized, no obvious indication).
    try:
        planned = _planned_claude_targets(project_root)
    except FileNotFoundError as e:
        print(f"warning: skill/agent scaffolding skipped — {e}", flush=True)
        planned = []
    conflicts = [p for p in planned if p.exists()]
    if conflicts:
        print(
            "error: refusing to overwrite existing skill/agent entries under .claude/:",
            flush=True,
        )
        for p in conflicts:
            print(f"  {p.relative_to(project_root)}", flush=True)
        print(
            "\nDelete or move them and re-run `sqa-tool init` if you want fresh "
            "bundled defaults.\nOtherwise, leave them in place — sqa-tool does "
            "not modify your customized skills/agents.",
            flush=True,
        )
        return 1

    sqa.mkdir(parents=True)
    paths.findings_dir(project_root).mkdir()
    paths.config_path(project_root).write_text(DEFAULT_CONFIG_TEXT)
    paths.file_status_path(project_root).write_text("{}\n")

    print(f"Initialized {sqa.relative_to(project_root)}/", flush=True)

    try:
        installed = _scaffold_claude_dirs(project_root)
    except FileNotFoundError as e:
        print(f"warning: skill/agent scaffolding skipped — {e}", flush=True)
        installed = []

    if installed:
        print(f"Installed {len(installed)} skill/agent entry(s) under .claude/:", flush=True)
        for p in installed:
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
