"""sqa-tool init — scaffold .sqa/ and Claude Code skill/agent dirs in the current project."""

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqa_tool import git_ops, paths
from sqa_tool.config import DEFAULT_CONFIG_TEXT


@dataclass(frozen=True)
class BundledEntry:
    """One bundled file scheduled for installation into `.claude/`."""

    src: Path
    dst: Path
    is_framework: bool


@dataclass
class InstallReport:
    """Project-relative paths affected by `_install_entries`.

    Five buckets cover the four-quadrant cross of (framework | project) ×
    (existed | didn't), plus a "framework existed but the bytes were
    already current" case. Distinguishing the no-op from the genuine
    update keeps re-runs from claiming to have changed files that
    actually weren't touched.
    """

    framework_installed: list[str] = field(default_factory=list)
    framework_updated: list[str] = field(default_factory=list)
    framework_unchanged: list[str] = field(default_factory=list)
    project_installed: list[str] = field(default_factory=list)
    project_preserved: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BootstrapResult:
    """Outcome of `_bootstrap_sqa`.

    `abort_code` is `None` on success and an exit code when init must abort.
    `fresh_init` is `True` iff `.sqa/` was just created by this call.
    """

    abort_code: int | None
    fresh_init: bool


# Agents whose primary `<name>.md` file is the framework agent. Any other
# `.md` file in `agents/` (e.g. `review-file-prompt.md`,
# `triage-guidelines.md`) is project-specific configuration that the
# framework agent reads at runtime.
_FRAMEWORK_AGENT_STEMS = frozenset(
    {
        "review-file",
        "triage-file",
        "resolve-file",
        "triage-general",
        "resolve-general",
    }
)

# Suffixes on agent `.md` filenames that mark project-specific companion files
# read by the framework agents at runtime. `-prompt` and `-guidelines` are
# the conventions; the legacy plural `-prompts` is also accepted so a
# partially-migrated checkout doesn't trip the classifier.
#
# This tuple is not consulted by the install logic — runtime classification
# is purely "stem in `_FRAMEWORK_AGENT_STEMS` ? framework : project-specific"
# (see `_is_framework_agent_file`). The tuple's sole consumer is the
# build-time consistency check `test_framework_agent_stems_covers_all_framework_files`
# in `tests/test_commands.py`, which enforces the suffix convention on
# bundled files so a stray `notes.md` can't sneak in as project-specific.
_PROJECT_AGENT_SUFFIXES = ("-prompt", "-prompts", "-guidelines")


# Header used by `_print_post_init_guidance` to introduce newly-installed
# project files on a re-init that added defaults (the upgrade framing).
# Factored out so tests in `tests/test_commands.py` can assert on the same
# literal without drift — analogous to the install-report banner strings
# the tests already share with their own module-level constants.
_NEW_PROJECT_FILES_HEADER = "New project-specific file(s) to tailor:"


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
    (e.g. `review-file-prompt.md`, `triage-guidelines.md`) is
    project-specific."""
    return stem in _FRAMEWORK_AGENT_STEMS


def _bundled_claude_entries(project_root: Path) -> list[BundledEntry]:
    """Yield a `BundledEntry` for every bundled skill/agent file.

    Framework files are overwritten by `init`; project-specific files are
    preserved when they already exist (created when they don't).

    For skills: walks the top level of `skills/<name>/` (one level — nested
    files are not picked up). `SKILL.md` is framework; everything else
    (e.g. `project.md`) is project-specific.

    For agents: walks `agents/` for `.md` files. Files whose stem is in
    `_FRAMEWORK_AGENT_STEMS` are framework; anything else is treated as
    project-specific. By convention the project-specific files carry
    `-prompt` / `-guidelines` suffixes, but that convention is enforced
    at build time by a test (see `_PROJECT_AGENT_SUFFIXES`), not at
    install time — the runtime rule is permissive on purpose.
    """
    entries: list[BundledEntry] = []

    skills_src = _bundled_dir("skills")
    skills_dst_root = project_root / ".claude" / "skills"
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir():
            continue
        # Skills are deliberately flat — one SKILL.md plus optional sibling
        # project files (e.g. project.md). Nested helpers are not part of the
        # bundle layout; if a skill grows that complex, restructure it rather
        # than walk recursively here. The same shape applies to the agents/
        # loop below.
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

    Framework files: written when missing or when bundled content differs
    from the existing destination. A byte-identical destination is left
    alone — no copy, no mtime bump — and reported as ``framework_unchanged``
    so re-runs can report honestly that they didn't change anything.

    Project files: written only when the target doesn't exist (newly
    installed defaults). Existing project files are preserved untouched
    because the user has likely customized them.

    The returned `InstallReport` distinguishes:
      - framework_installed: framework file didn't exist locally; just copied.
      - framework_updated: existed, bundled bytes differed, just upgraded.
      - framework_unchanged: existed, bundled bytes identical; no copy needed.
      - project_installed: project default just installed (no prior file).
      - project_preserved: project file existed; left in place as the user's.
    """
    report = InstallReport()

    for entry in entries:
        entry.dst.parent.mkdir(parents=True, exist_ok=True)
        rel = str(entry.dst.relative_to(project_root))
        if entry.is_framework:
            if entry.dst.exists():
                # Compare bytes before copying so a re-run with no bundled
                # changes neither rewrites the file nor reports it as
                # updated. These are kilobyte-scale markdown files; the
                # extra read is cheap and the no-op honesty is the whole
                # point.
                if entry.dst.read_bytes() == entry.src.read_bytes():
                    report.framework_unchanged.append(rel)
                    continue
                shutil.copy2(entry.src, entry.dst)
                report.framework_updated.append(rel)
            else:
                shutil.copy2(entry.src, entry.dst)
                report.framework_installed.append(rel)
        else:
            if entry.dst.exists():
                report.project_preserved.append(rel)
                continue
            shutil.copy2(entry.src, entry.dst)
            report.project_installed.append(rel)

    return report


def _bootstrap_sqa(project_root: Path) -> BootstrapResult:
    """Create `.sqa/` if absent, or verify it is complete."""
    sqa = paths.sqa_dir(project_root)
    sqa_rel = sqa.relative_to(project_root)

    if not sqa.exists():
        sqa.mkdir(parents=True)
        paths.config_path(project_root).write_text(DEFAULT_CONFIG_TEXT)
        paths.file_status_path(project_root).write_text("{}\n")
        print(f"Initialized {sqa_rel}/", flush=True)
        return BootstrapResult(abort_code=None, fresh_init=True)

    config_path = paths.config_path(project_root)
    file_status_path = paths.file_status_path(project_root)
    missing: list[str] = []
    if not config_path.is_file():
        missing.append(str(config_path.relative_to(project_root)))
    if not file_status_path.is_file():
        missing.append(str(file_status_path.relative_to(project_root)))
    if missing:
        print(
            f"error: {sqa_rel}/ exists but is incomplete. "
            f"Missing: {', '.join(missing)}. "
            f"Restore the missing item(s) (e.g. from version control if "
            f"tracked), or remove {sqa_rel}/ entirely to re-initialize "
            f"from scratch.",
            file=sys.stderr,
            flush=True,
        )
        return BootstrapResult(abort_code=1, fresh_init=False)
    print(
        f"{sqa_rel}/ already exists; preserving project state. "
        "Refreshing skill/agent framework files only.",
        flush=True,
    )
    return BootstrapResult(abort_code=None, fresh_init=False)


def _print_install_report(report: InstallReport) -> None:
    """Emit one section per non-empty bucket in the install report.

    Conventions:
      - ``framework_installed`` / ``framework_updated`` / ``project_installed``
        / ``project_preserved`` enumerate paths — those are the changes the
        user might want to inspect or react to.
      - ``framework_unchanged`` is summarized as a single line with a count.
        Listing files that didn't change is noise; the count is enough
        confirmation that the framework is current.
    """
    if report.framework_installed:
        print(f"\nInstalled {len(report.framework_installed)} framework file(s):", flush=True)
        for p in report.framework_installed:
            print(f"  {p}", flush=True)

    if report.framework_updated:
        print(
            f"\nUpdated {len(report.framework_updated)} framework file(s) "
            "(upgraded to current bundled version):",
            flush=True,
        )
        for p in report.framework_updated:
            print(f"  {p}", flush=True)

    if report.framework_unchanged:
        # Summary line only — these are the no-op case and don't need
        # per-file enumeration.
        print(
            f"\nFramework already current: {len(report.framework_unchanged)} file(s).",
            flush=True,
        )

    if report.project_installed:
        print(
            f"\nInstalled {len(report.project_installed)} project-specific file(s) "
            "(defaults — edit to tailor):",
            flush=True,
        )
        for p in report.project_installed:
            print(f"  {p}", flush=True)

    if report.project_preserved:
        print(
            f"\nPreserved {len(report.project_preserved)} project-specific file(s) "
            "(your customizations untouched):",
            flush=True,
        )
        for p in report.project_preserved:
            print(f"  {p}", flush=True)


# Bundled-default filenames that earlier versions of the tool installed
# into `.claude/agents/`, kept here so re-init in a project from an older
# install surfaces them in the legacy warning rather than silently
# treating them as project-specific files.
_LEGACY_FILE_BASENAMES = frozenset(
    {
        "review-file-prompts.md",  # plural → singular rename
        "triage-file-guidelines.md",  # renamed to triage-guidelines.md
        "fix-orphans.md",  # subagent removed when the orphans flow was retired
    }
)


# Directory names that the legacy-artifact scan filters out of its `.sqa.md`
# hits so unrelated trees (nested repos, virtualenvs, vendored dependencies,
# build caches) aren't surfaced as legacy artifacts of the current project.
_LEGACY_SCAN_SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}
)


def _legacy_artifacts(project_root: Path) -> list[str]:
    """Locate state from earlier installs of this tool that the current
    version no longer uses.

    Reported but never touched — the legacy data could be a user's
    in-flight work, and the tool doesn't speak for the user about when
    it's safe to delete. Surfaces:
      - `.sqa/findings/` (the old per-finding store)
      - any `.sqa.md` file anywhere in the tree (old higher-scope anchors)
      - old agent filenames from prior bundled defaults

    Returns project-relative path strings; an empty list means no legacy
    state was found.
    """
    findings_dir = paths.sqa_dir(project_root) / "findings"
    found: list[str] = []
    if findings_dir.is_dir():
        found.append(str(findings_dir.relative_to(project_root)) + "/")
    # `.sqa.md` could live anywhere; walk once. rglob walks the whole tree;
    # the skip_dirs filter discards hits inside .git/, .venv/, node_modules/,
    # etc. so we don't surface them as legacy artifacts of the current
    # project (they belong to nested repos or vendored trees). This is about
    # result correctness, not perf — rglob still descends into the ignored
    # dirs, the filter just discards their hits.
    for child in project_root.rglob(".sqa.md"):
        if any(part in _LEGACY_SCAN_SKIP_DIRS for part in child.parts):
            continue
        found.append(str(child.relative_to(project_root)))
    # Old agent filenames in `.claude/agents/`.
    agents_dir = project_root / ".claude" / "agents"
    if agents_dir.is_dir():
        for name in sorted(_LEGACY_FILE_BASENAMES):
            f = agents_dir / name
            if f.is_file():
                found.append(str(f.relative_to(project_root)))
    return found


def _print_legacy_warning(legacy: list[str]) -> None:
    """Emit a warning section listing legacy artifacts found in the project.

    No automatic cleanup — the user decides when to remove these. The
    warning makes their presence visible so an upgraded install doesn't
    behave confusingly (e.g. with stale `.sqa.md` files lingering, or an
    old `findings/` directory consuming disk).
    """
    print("", flush=True)
    print(
        "Note: artifacts from an earlier version of this tool were found.\n"
        "The current version doesn't use them; they're left in place so\n"
        "you can clean up at your own pace:",
        flush=True,
    )
    for p in legacy:
        print(f"  {p}", flush=True)
    print(
        "Safe to delete once you're confident no in-flight review depends on them.",
        flush=True,
    )


def _print_post_init_guidance(report: InstallReport, fresh_init: bool) -> None:
    """Emit the gitignore note (only on fresh init) and the "edit to tailor"
    section (only when there are newly-installed project files).

    The "edit to tailor" call-to-action is conditional on
    ``report.project_installed``. Re-runs that didn't install any new
    project files don't get the directive — the user has already tuned
    their existing files, and pointing at them again with "edit to
    tailor" is misleading.

    On fresh init, every project file is newly installed, so the section
    naturally fires with the full default-set listing. On an upgrade that
    happens to add a new project default (e.g. a new agent's
    ``*-prompt.md`` shipping in a tool upgrade), the section fires with
    just the new file(s). On a vanilla re-run with no new project files,
    the section is omitted entirely.
    """
    if fresh_init:
        print("", flush=True)
        print(
            "Note: review result files land in .sqa/result_<timestamp>.json. The\n"
            "default .gitignore recommendation is `.sqa/result*.json` — result\n"
            "files quote source and are per-session, so the audit value is lower\n"
            "than tracked files would warrant. Track them deliberately if you\n"
            "want a git-versioned history of reviews.",
            flush=True,
        )
    if report.project_installed:
        print("", flush=True)
        if fresh_init:
            # Fresh-init framing: situate the files in the broader picture
            # since the user is seeing them for the first time.
            header = (
                "Project-specific configuration (quality-check command, review prompts,\n"
                "triage guidelines) lives in:"
            )
        else:
            # Upgrade framing: just the new defaults that landed in this
            # re-run, in a tighter form.
            header = _NEW_PROJECT_FILES_HEADER
        print(header, flush=True)
        for p in report.project_installed:
            print(f"  {p}", flush=True)
        print(
            "Edit those to tailor the system to your project. They are preserved\n"
            "across `sqa-tool init` upgrades; the framework files (SKILL.md,\n"
            "<agent>.md) are kept current automatically.",
            flush=True,
        )


def _preflight(project_root: Path) -> int | None:
    """Validate that `project_root` is a sensible target for `init`.

    `init` doesn't require an existing `.sqa/`, but it does require a git
    repository with at least one commit — the reviewer's change-detection
    relies on `git ls-files` and blob hashing, neither of which produces
    useful output before the first commit.

    Returns ``None`` on success and an exit code (1) when init must abort,
    after printing a user-facing error to stderr.
    """
    if not git_ops.is_repo(project_root):
        print(
            "error: sqa-tool requires a git repository. Run `git init` first, "
            "stage and commit your initial files, then try again.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    if not git_ops.has_commits(project_root):
        print(
            "error: this git repository has no commits yet. The reviewer needs "
            "at least one commit because change detection works against tracked "
            "files. Run `git add .` and `git commit -m 'initial'`, then try again.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    return None


def run(project_root: Path) -> int:
    """Run `sqa-tool init` against `project_root`.

    The flow is:
      1. Preflight: verify `project_root` is a git repository with at
         least one commit (the reviewer's change-detection requires it).
      2. Bootstrap `.sqa/` — create it from scratch (fresh init) or verify
         that an existing `.sqa/` is complete; abort if it is incomplete.
      3. Install bundled `.claude/` skill and agent files, overwriting
         framework files and preserving any project-specific customizations.
      4. Print an install report and post-init guidance (gitignore note on
         fresh init, list of project-specific files to tailor, warning
         about any leftover artifacts from earlier installs).

    Returns 0 on success, or a nonzero abort code from `_preflight` /
    `_bootstrap_sqa`.
    """
    preflight_rc = _preflight(project_root)
    if preflight_rc is not None:
        return preflight_rc

    bootstrap = _bootstrap_sqa(project_root)
    if bootstrap.abort_code is not None:
        return bootstrap.abort_code
    fresh_init = bootstrap.fresh_init

    # Note on ordering: `_bootstrap_sqa` above has already created `.sqa/`
    # if this is a fresh init. If the bundled-scaffold lookup below raises
    # FileNotFoundError, `.sqa/` is left in place; this is intentional. The
    # user's remedy is to reinstall the package, not to recreate `.sqa/`,
    # and a retry will hit the "already exists" branch in `_bootstrap_sqa`
    # and proceed to install `.claude/` normally. The partial state is
    # benign — no findings, no project config to lose.
    try:
        entries = _bundled_claude_entries(project_root)
    except FileNotFoundError as e:
        print(
            f"error: bundled skill/agent scaffolding could not be located — {e}\n"
            "This usually means the installed sqa-tool package is missing its "
            "bundled `skills/` and `agents/` directories. Reinstall the package "
            "(e.g. `uv tool install --reinstall sqa-tool`) and run "
            "`sqa-tool init` again.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    report = _install_entries(project_root, entries)
    _print_install_report(report)
    _print_post_init_guidance(report, fresh_init)

    legacy = _legacy_artifacts(project_root)
    if legacy:
        _print_legacy_warning(legacy)

    return 0
