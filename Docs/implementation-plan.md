# Reviewer v2 — Implementation Plan

Companion to [`design.md`](./design.md). Plans the order of work, defines an MVP, and identifies decisions to make during implementation rather than design.

## Guiding principles

- **Bottom-up, testable layers.** Each milestone leaves the codebase in a working, testable state. No half-built layer is checked in waiting on a higher one.
- **Deterministic core first, agentic surface last.** The CLI tool is the load-bearing piece; the skills are markdown that comes together quickly once the tool is solid.
- **Defer aggressively.** Anything in the design's "Open questions" section stays deferred unless implementation makes it cheap to include.
- **Mirror v1's stack where reasonable.** Python 3.12+, `uv` for tooling, `pytest`, `ruff`. Saves bikeshedding.

## Project scaffolding

```
Reviewer2/
├── README.md                       # short, points at design.md
├── LICENSE                         # MIT, same as v1
├── pyproject.toml                  # uv-managed, console-script entry for sqa-tool
├── runtools.sh                     # convenience wrapper (lint/type/test)
├── src/
│   └── sqa_tool/
│       ├── __init__.py
│       ├── cli.py                  # argparse dispatch, subcommand glue
│       ├── config.py               # .sqa/config.toml loading
│       ├── paths.py                # find_sqa_dir, project root, etc.
│       ├── git_ops.py              # blob hashing, ls-files, diff
│       ├── findings.py             # Finding dataclass, JSON read/write, ID alloc
│       ├── anchors.py              # per-language table, grep, insertion
│       ├── file_status.py          # fcntl-locked status file
│       ├── scope.py                # scope rule, findings-for-file logic
│       ├── orphans.py              # auto-fix + reporting
│       └── commands/
│           ├── init.py
│           ├── needs_review.py
│           ├── mark_reviewed.py
│           ├── record_finding.py
│           ├── triage.py           # triage, resolve, reopen
│           ├── show.py             # show-finding, list-findings, status
│           ├── findings_for_file.py
│           ├── orphans.py
│           ├── gc.py
│           └── diff_since_review.py
├── skills/                         # bundled defaults; init copies these
│   ├── sqa-review.md
│   ├── sqa-resolve.md
│   └── sqa-status.md
├── agents/                         # bundled defaults; init copies these
│   ├── review-file.md
│   ├── triage-file.md
│   ├── resolve-file.md
│   └── fix-orphans.md
├── Docs/
│   ├── design.md                   # already exists
│   └── implementation-plan.md      # this doc
└── tests/
    ├── conftest.py                 # fixture: temp project repo
    └── test_*.py                   # one per module under src/
```

## Milestones

Each milestone ends with green tests and a usable increment. Roughly sized; not absolute.

### M1 — Foundation + minimal record/show

**Deliverables:**
- Project scaffolding, `pyproject.toml`, console-script entry `sqa-tool`.
- `init` subcommand: creates `.sqa/` with `config.toml`, `findings/`, empty `file_status.json`. Logs the gitignore note. Skips skill/agent scaffolding for now (M5 territory).
- `record-finding` subcommand: allocates random base32 ID, writes `findings/<id>.json`, optionally inserts anchor under fcntl lock when `--anchor` is passed.
- `show-finding`, `list-findings` subcommands.
- Anchor module: per-language comment table, anchor regex, comment-syntax-aware insertion.
- Tests: ID allocation (collisions, format), JSON shape round-trip, anchor insertion across languages, list filtering.

**Out of M1:** scope-aware queries, hash tracking, orphans, skills.

**Done means:** I can `sqa-tool init`, `sqa-tool record-finding ...`, see findings on disk, list them, and have an anchor comment land in the right file with the right syntax.

### M2 — Hash tracking + scope-aware lookup

**Deliverables:**
- `git_ops.py`: blob hashing via `git hash-object --stdin-paths`, `git ls-files` filtering, project-relative path normalization.
- `file_status.py`: fcntl-locked read-modify-write of `.sqa/file_status.json`.
- `needs-review` (with `--count`, `--limit N`).
- `mark-reviewed`.
- `findings-for-file`: walks anchor presence + ancestor `.sqa.md` scope, filtered by `related_files` match.
- `diff-since-review`.
- Tests: rename detection, stale entry pruning, scope-walk correctness, concurrent writes (multiprocess fixture).

**Done means:** I can run a manual review loop — modify a file, run `needs-review`, get findings-for-file, manually `record-finding`, `mark-reviewed`, and the next `needs-review` correctly excludes that file.

### M3 — State transitions + status

**Deliverables:**
- `triage`, `resolve`, `reopen` (rationale-replacing).
- `status` subcommand: counts and breakdowns (per directory, per severity).
- Anchor *removal* on `resolve` (the inverse of insertion).
- Tests: state machine (open → triaged → resolved; reopen path), rationale replacement is full-string, anchor removal is clean.

**Done means:** the full lifecycle of a finding works end-to-end via tool subcommands.

### M4 — Maintenance commands

**Deliverables:**
- `orphans`: deterministic auto-fixes (empty `.sqa.md`, anchor-file missing from `related_files`); reports for the rest.
- `gc --older-than=<duration>`: prunes resolved findings.
- Tests: each orphan class detected/fixed correctly; gc respects the duration window and only touches `resolved`.

**Done means:** the tool can self-maintain a `.sqa/` tree across renames, deletions, and accumulated resolved findings.

### M5 — Skills + subagents

**Deliverables:**
- Bundled `skills/sqa-{review,resolve,status}.md` with prompts for the loop pattern, batching, parallel subagent dispatch, optional quality-check command, summary via `sqa-tool status`.
- Bundled `agents/{review-file,triage-file,resolve-file,fix-orphans}.md` with embedded review-prompt sections (port from v1's `file_review_prompts.md` as starting content).
- `init` scaffolds these into the project's harness skill/agent directories.
- Manual end-to-end testing on this repo (dogfooding) — ironic but real signal.

**Done means:** `/sqa-review` end-to-end produces findings, `/sqa-resolve auto` triages and fixes, `/sqa-status` reports.

### M6 — Polish

**Deliverables:**
- Distribution: `uv tool install` parity with v1.
- `README.md` with quickstart.
- Final pass on error messages and help text.
- CI workflow (mirror v1's `.github/workflows/ci.yml`).

## Decisions to make during implementation

These don't block design but want resolution before they cause refactors:

- **Anchor insertion point in source files (when LLM doesn't pick).** When `record-finding --anchor=foo.py` is called for a source file (not `.sqa.md`), where does the tool put the comment? Options: top of file, end of file, before/after the matching symbol if one is named. Simplest: top of file (after any shebang or imports block). Revisit if it's awkward.
- **`sqa-tool` invocation from skills.** Skills will call `sqa-tool ...` via Bash. We need to ensure `sqa-tool` is on PATH when `uv tool install`-ed; verify the entry-point declaration in `pyproject.toml` matches.
- **Per-language comment table location.** Hard-coded in `anchors.py` is fine for MVP. If users want to extend it without code changes, expose via `config.toml`. Defer.
- **Concurrency tests.** fcntl behavior on different platforms (Linux/Mac/WSL) needs at least one cross-process test to verify. Use `pytest`'s subprocess fixtures.
- **What `diff-since-review` actually returns when there's no prior hash.** Probably the full file (treat as "diff against empty"). Document.

## Explicitly deferred (from design `Open questions`)

- `related_files` glob support — start with literal paths.
- Diff-scoped review prompts — just whole-file for v2 MVP.
- `reconcile` subcommand — manual recovery is fine for now.
- `--private` flag and severity-routed private storage — wait for real demand.
- Cross-cutting finding handler — single-file dispatch pattern is good enough.
- Section-at-a-time prompt structure A/B with v1 — measure once we have something to compare.

## Risks / things to watch

- **Anchor insertion correctness across languages.** Especially trailing-comment placement (e.g. JS object literals where a trailing `// sqa:` could end up inside a string by accident). Worth fuzz-testing.
- **fcntl on weird filesystems.** Some network-mounted filesystems (NFS) handle locking poorly. Document Linux/Mac/WSL local FS as supported; treat NFS as best-effort.
- **Skill prompt length.** Embedding all the per-file review sections in `agents/review-file.md` could make the prompt large. If it bloats agent context, split sections out into files the subagent reads on demand.
- **Token cost of full-file context per review.** Same as v1; if it bites, the diff-scoped path opens up.

## Initial commit / first PR

Once M1 is in: open as a draft PR with the full project scaffolding and the M1 deliverables. Subsequent milestones go in as separate PRs onto the same branch (or main, if we're not branching).

---

Open the implementation by:

1. Creating `pyproject.toml`, `README.md`, `LICENSE`, `runtools.sh`, the `src/sqa_tool/` skeleton, the `tests/` skeleton.
2. Implementing M1 in order: scaffolding → `init` → anchor module → `record-finding` → `show-finding` / `list-findings` → tests.
3. Open the first PR.

After that, M2–M6 in order, each behind its own PR.
