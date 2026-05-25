# Design

A code reviewer built on Claude Code skills and a small deterministic CLI.
The agentic surface is a cluster of skills (`/sqa-review`, `/sqa-resolve`,
`/sqa-status`) that fan out to per-file subagents; load-bearing
bookkeeping (change detection, finding storage, schema enforcement, state-
machine transitions) lives behind a Python CLI (`sqa-tool`).

This document is the source of truth for the design. Implementation details
that don't change the architectural picture are out of scope here.

---

## 1. Motivation

The job of the reviewer is to:

1. Identify quality issues in tracked source files — bugs, smells, missing
   docs, inconsistencies — at a level that's worth a human (or LLM
   reviewer) reading carefully and exercising judgment.
2. Classify each issue into one of three buckets: things to fix
   autonomously, things to walk through with the user, and things to leave
   alone (with a rationale).
3. Apply fixes for the autonomous bucket; offer a guided multi-turn
   conversation for the interactive bucket.

Two design pivots shape the rest of the document:

- **Skills + a deterministic CLI, not a Python harness.** The user-facing
  verbs (`/sqa-review`, `/sqa-resolve`, `/sqa-status`) are Claude Code
  skills. The skills call out to a small CLI tool (`sqa-tool`) for all
  state-mutating work; they don't reach into JSON or git state directly.
  This keeps the agentic surface in markdown — easy to inspect, easy to
  customize per project — and the deterministic surface in Python where
  it's testable.

- **Per-run result files, not persistent findings.** Each review session
  writes one `.sqa/result_<timestamp>.json` containing every finding
  recorded that session, every triage decision, every status transition.
  No durable per-finding records, no in-source anchor comments tying code
  back to finding IDs. Design intent that should outlive a single review
  session is captured as **defensive comments in source**, written at
  resolve time — a comment in the code, near the code it explains, that
  future reviewers see naturally.

## 2. Goals & non-goals

### Goals

- Bookkeeping is deterministic and testable; judgment is agentic.
- Skill-driven UX, harness-native: no SDK lock-in, no Python orchestration
  in the user's path.
- Scales to projects with hundreds of files and dozens of findings per
  session.
- Project-customizable without forking: the review prompt, triage
  guidelines, and per-project quality-check command are project-owned
  files preserved across tool upgrades.
- Concurrent-write safe: parallel subagents recording findings or
  classifying them don't corrupt the result file.

### Non-goals

- Cross-repo finding aggregation.
- A web UI / dashboard. Findings are inspected via CLI and `git`.
- Persistent finding records across sessions. (See § 8 for the rationale,
  and § 11 for the opt-in path if this turns out to matter.)

## 3. Architecture summary

```
┌────────────────────────────────────────────────────────────────┐
│ User-facing skills (markdown, harness-loaded)                  │
│   sqa-review   — run a review pass                             │
│   sqa-resolve  — triage + fix findings (auto or interactive)   │
│   sqa-status   — report on finding state                       │
└────────────────────────────────────────────────────────────────┘
                          │
                          │ invokes
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ Subagents (markdown in agents/)                                │
│   review-file      — review one file                           │
│   triage-file      — triage findings on one file               │
│   resolve-file     — fix all auto-class findings on one file   │
│   triage-general   — triage `file == null` findings            │
│   resolve-general  — fix all auto-class general findings       │
└────────────────────────────────────────────────────────────────┘
                          │
                          │ all state changes
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ sqa-tool (deterministic CLI)                                   │
│   Session lifecycle:                                           │
│     start-result, active-result, categories                    │
│   Change detection:                                            │
│     needs-review, mark-reviewed, diff-since-review             │
│   Findings (operate on the active result file):                │
│     record-finding, triage, resolve,                           │
│     show-finding, list-findings, findings-for-file, status     │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ On-disk state                                                  │
│   .sqa/                                                        │
│     config.toml             — include/exclude globs + category │
│                               list                             │
│     file_status.json        — per-file last-reviewed git hash  │
│                               (fcntl-locked for concurrent     │
│                                writes)                         │
│     result_<timestamp>.json — one per review session           │
│                               (fcntl-locked for concurrent     │
│                                writes)                         │
└────────────────────────────────────────────────────────────────┘
```

The CLI owns *state*. Skills and subagents own *judgment*. They never edit
state files directly — always via `sqa-tool`.

## 4. Storage model

### 4.1 Result files

Every `/sqa-review` invocation creates a fresh result file at
`.sqa/result_<YYYY_MM_DD_HHMMSS>.json` and starts recording findings into
it. The file accumulates state through the session: review records,
triage decisions, resolve transitions. Nothing is deleted along the way —
`resolve` flips `status`; the entry stays for the record.

The "active" result file is the most recent one by lexical filename order
(which matches creation order given the timestamp suffix). Mutating
commands (`record-finding`, `triage`, `resolve`) operate on the active
result; they refuse to touch historical results. Read commands default to
the active result and accept `--from <path>` to inspect an older one
(historical results are read-only).

This per-run model is intentional. Persistent finding records (the
alternative — keep one JSON per finding across sessions, with in-source
anchor comments pointing back) buy "the reviewer sees what we decided
last time" at the cost of meaningful machinery: anchor placement, orphan
reconciliation when files move, schema migrations, anchor debris in
source. The per-run model trades that machinery for a different mechanism
— **defensive comments**, § 6.4 — that puts rationale where the next
reviewer will naturally find it.

### 4.2 Result file shape

```json
{
  "version": 2,
  "timestamp": "2026_05_25_142318",
  "total": 17,
  "findings": [
    {
      "id": 1,
      "category": "error-handling",
      "file": "src/auth/login.py",
      "line": 42,
      "quoted_text": "raise Exception(\"login failed\")",
      "message": "Session-creation path raises bare Exception; rest of the module uses AuthError. Standardize on AuthError.",
      "severity": "warning",
      "triage": "auto",
      "rationale": "AuthError is already imported and used elsewhere in the module. Replace the bare Exception with AuthError on this line; no other changes needed.",
      "status": "open",
      "related": []
    }
  ]
}
```

Field reference:

| Field | Notes |
|---|---|
| `id` | Per-result-file sequential integer. Starts at 1; no need for global uniqueness across sessions. |
| `category` | One of the project's review categories (see § 5.1). Soft label — `--category` accepts any string with a warning if it's outside the configured list. |
| `file` | Project-relative path. `null` for project-wide findings that don't anchor to a single file. |
| `line` | Optional. Line in `file` at recording time — the **primary locator** alongside `file`. May drift as fixes shift lines during a resolve pass; the resolver handles that. |
| `quoted_text` | Optional short excerpt (≤ ~3 lines) of the offending code. Supplementary locator that helps disambiguate when the line has drifted, and makes the result file readable on its own. Not a definitive "if-not-found-then-already-resolved" signal — auto-resolve may have altered quoted code while fixing a *different* finding on the same lines. |
| `message` | The finding itself, in prose. |
| `severity` | `info` \| `warning` \| `error`. |
| `triage` | `null` (untriaged) \| `auto` \| `interactive` \| `ignore`. |
| `rationale` | Current-state reasoning. For `auto`-triaged findings, includes the resolve hint — what to change and why. For `interactive`, what needs human input. For `ignore`, the specific reason no action applies. Replaced wholesale on every state change; the LLM keeps it coherent. |
| `status` | `open` \| `resolved`. See § 4.3 for the state machine. |
| `related` | Optional list of additional files the finding concerns. Used for multi-file findings (e.g. a DRY violation spanning `foo.py` and `bar.py`). `findings-for-file` matches on `file` *or* `related`. |

**Ordering.** Findings in the JSON array are stored in `id` order
(1, 2, 3, …). IDs are allocated sequentially at `record-finding` time;
under parallel review, allocation order matches commit order under the
result-file lock (§ 4.5).

**ID scoping.** IDs are scoped to a single result file. `sqa-tool resolve 5`
resolves finding 5 in the active result; with `--from=<path>`, IDs are
scoped to that file. There is no cross-file ID space.

### 4.3 Triage / status state machine

Five valid states; `untriaged+resolved` and `ignore+open` are illegal at
the storage boundary (the loader rejects them).

| Current state                  | `triage ignore`         | `triage auto` / `triage interactive` | `resolve`               |
|---|---|---|---|
| `untriaged + open`             | → `ignore + resolved`   | → `auto`/`interactive` + `open`      | (rejected — triage first) |
| `auto + open`                  | → `ignore + resolved`   | → other + `open`                     | → `auto + resolved`     |
| `interactive + open`           | → `ignore + resolved`   | → other + `open`                     | → `interactive + resolved` |
| `ignore + resolved`            | (rationale update only) | → `auto`/`interactive` + `open` *(un-ignoring)* | (rejected — already resolved) |
| `auto`/`interactive` + `resolved` | rejected — no reopen | rejected — no reopen                 | (rejected — already resolved) |

Key invariants:

- **`triage ignore` always implies `status = resolved`** — same call, same
  transaction. `ignore` is a bookkeeping close, not a pending state.
- **Un-ignoring is permitted.** Re-triaging an `ignore + resolved` finding
  to `auto`/`interactive` flips status back to `open`. No code was changed
  on the way in (that's what `ignore` *means*), so there's nothing to
  undo.
- **No reopen of action-resolved findings.** Once `auto` or `interactive`
  resolution has actually edited code, the finding is terminal.
  Re-surfacing the concern means recording a fresh finding on the next
  review pass.

### 4.4 Locator: file + line + quoted_text

`file` + `line` is the primary locator. The resolver, given a target
file and line number, locates the finding's referent reliably even after
multiple prior fixes in the same session have shifted lines — large-batch
resolve runs were the validating case for this approach in earlier
generations of the tool.

`quoted_text` is supplementary: a short excerpt of the offending code,
recorded at review time. It helps disambiguate when several findings
cluster on overlapping lines and an earlier resolve has changed the code,
and it makes the result file readable on its own (you can see the
context without opening the source). It is not treated as a definitive
"if-not-found-then-already-resolved" signal — the resolver applies
judgment, since auto-resolve may have altered quoted text while fixing a
different finding nearby.

If quoting isn't natural (project-wide finding, or one about a missing
thing rather than an existing thing), `quoted_text` may be `null`.

### 4.5 Concurrent writes

Parallel subagents call `record-finding` (during review), `triage`
(during the autonomous triage phase), and read the active result via
`findings-for-file` and friends. Auto-resolve is serial, so only one
resolver at a time mutates the result file — but read commands still
run concurrently with it.

All mutations are serialized by an `fcntl` exclusive lock on the active
result file, held for the read-modify-write critical section. Lock
contention is negligible — each critical section is short (a JSON load,
an edit, a JSON dump on a kilobytes-scale file).

Linux/Mac/WSL only. Windows-native support is out of scope.

## 5. CLI surface

### 5.1 `.sqa/config.toml`

```toml
[files]
include = ["src/**/*.py"]
exclude = ["src/**/*_test.py"]

[categories]
# Canonical list of review categories. The review-file framework subagent
# fetches this list (via `sqa-tool categories`) and tags each finding with
# one. The CLI's --category flag uses it for soft validation (unknown
# values warn). The project review prompt itself stays tool-agnostic and
# doesn't mention this list.
list = [
  "dry-ssot",
  "interfaces",
  "logic",
  "comments",
  "error-handling",
  "kiss-yagni",
  "security",
  "project-specific",
]
```

That's all the configuration. No `[agent]` block (model selection is
harness-native), no `[tools]` block (skills invoke project-local checks
directly via Bash), no `[dispatch]` block (per-invocation parameters come
from skill arguments or interactive prompts).

Categories are tool-machinery, not review guidance. They live in
`config.toml` because that's the project's tool-configuration surface;
the project's review *content* lives in `review-file-prompt.md` and stays
tool-agnostic. The prompt could be handed to any reviewer, human or
otherwise — no mention of `sqa-tool` or category names in the prompt
itself.

### 5.2 Commands

Grouped by phase:

```
# Session lifecycle
sqa-tool init                                         # Scaffold .sqa/ and .claude/
sqa-tool start-result                                 # Begin a review session
sqa-tool active-result                                # Print path of most-recent result file
sqa-tool categories                                   # Print configured category list

# Change detection
sqa-tool needs-review [--count] [--limit N]           # List/count files needing review
sqa-tool mark-reviewed <path>                         # Record current blob hash
sqa-tool diff-since-review <path>                     # Diff vs last-reviewed blob

# Findings (mutating; operate on the active result file only)
sqa-tool record-finding --message=... --severity=... \
    --file=<path> [--line=N] [--quoted-text=...] \
    [--category=...] [--related=<path> ...] [--rationale=...]
sqa-tool triage <id> auto|interactive|ignore --rationale=...
sqa-tool resolve <id> --rationale=...

# Findings (read; default to active, accept --from for historical)
sqa-tool show-finding <id> [--from <path>]
sqa-tool list-findings [--triage=...] [--status=...] [--count] [--limit N] [--from <path>]
sqa-tool findings-for-file <path> [--from <path>]
sqa-tool status [--from <path>]
```

A few load-bearing details:

- **`start-result` is required before `record-finding`.** Once a session
  starts, every subagent recording findings writes into the same active
  result file — no per-subagent paths to coordinate.
- **`start-result` enforces a safety guard against mid-session rotation.**
  If the previous result file has any *open* findings, `start-result`
  refuses (exit 1) unless `--force` is passed. This catches the most
  damaging foot-gun in the model: a wayward subagent calling
  `start-result` during an in-progress review or resolve pass would
  silently rotate the "active" pointer and orphan every concurrent
  subagent's writes. Subagent prompts forbid the call; the CLI guard is
  the belt-and-suspenders. The legitimate "I abandoned last session and
  want a fresh one" case is unblocked by `--force` (the `sqa-review`
  skill surfaces the refusal to the user and asks before passing it).
- **`record-finding` enforces a safety guard against post-resolve
  writes.** Once any finding in the active result has
  `status == "resolved"`, `record-finding` refuses without `--force`.
  This catches the inverse mistake: someone running review on top of a
  partially-resolved result.
- **`triage ignore` flips status in the same call.** No separate
  `resolve` step is needed for ignored findings; that's the state
  machine in § 4.3.
- **`resolve` does not delete.** It transitions `status` to `resolved`.
  The finding entry stays for the record.
- **Soft category validation.** `record-finding --category=foo` accepts
  any string, but warns to stderr if `foo` isn't in the configured list.

### 5.3 Next-step hints

The loop-gate commands (those a skill polls to decide what to do next)
print a one-line `hint:` suggestion to **stderr** when called with
`--count`. Stdout stays pure (a parseable integer) so shell capture
(`$(sqa-tool needs-review --count)`) keeps working.

Hinted commands:

- `needs-review --count` — hint about dispatching `review-file` subagents
  vs. finishing the pass.
- `list-findings --triage=untriaged --count` — hint about dispatching
  `triage-file` / `triage-general` vs. proceeding to resolve.
- `list-findings --triage=auto --status=open --count` — hint about serial
  `resolve-file` dispatch.
- `list-findings --triage=interactive --status=open --count` — hint about
  the interactive walk.

The hints exist to keep the loop agent oriented across many iterations
without it needing to re-read the skill markdown each turn. Other
`list-findings --count` queries don't trigger hints (too generic to
suggest a single next step).

### 5.4 `--from` value resolution

- Absolute paths and paths containing a separator are used as-is
  (relative paths are interpreted against cwd).
- A bare filename (no separator) is resolved against `.sqa/`.

So `--from=result_2026_05_24_142318.json`,
`--from=.sqa/result_2026_05_24_142318.json`, and
`--from=/abs/path/to/result.json` all work.

## 6. Skill / subagent layout

### 6.1 Skills

Three skills, each owning one user-visible verb. The `sqa-` prefix avoids
collision with Claude Code's built-in `/review` slash command.

**Installation model.** Skills and subagents are installed per-project,
scaffolded by `sqa-tool init` into the project's `.claude/` directory.
Each skill or subagent that has project-customizable content is split
into two files:

- A **framework file** that holds the workflow logic — what tools to
  call, in what order, dispatch patterns.
- A **project file** that holds project-specific configuration — the
  quality-check command, review prompt content, triage guidelines.

Layout:

```
.claude/skills/
  sqa-review/
    SKILL.md           ← framework (overwritten by init)
    project.md         ← project-specific (preserved by init)
  sqa-resolve/
    SKILL.md           ← framework
    project.md         ← project-specific
  sqa-status/
    SKILL.md           ← framework only

.claude/agents/
  review-file.md             ← framework
  review-file-prompt.md      ← project-specific (the review guidance)
  triage-file.md             ← framework
  triage-general.md          ← framework
  triage-guidelines.md       ← project-specific (triage criteria)
  resolve-file.md            ← framework
  resolve-general.md         ← framework
```

Framework files are overwritten on every `sqa-tool init` (so users get
the latest workflow logic). Project files are preserved if they exist
and created from bundled defaults if they don't. The discrimination rule
for agents: files whose stem is in the canonical framework-agent set
(`review-file`, `triage-file`, `resolve-file`, `triage-general`,
`resolve-general`) are framework; files with a project-file suffix
(`-prompt`, `-guidelines`) are project-specific.

#### `sqa-review`

One invocation handles a complete review under normal circumstances.

1. Read project configuration (`project.md`) for the quality-check
   command and project conventions.
2. Pre-review quality check. If the deterministic tools fail, stop and
   surface — the reviewer's value is in finding things tools miss.
3. `sqa-tool start-result` to begin a fresh session (also prints the
   project's category list, for the skill to echo back to the user).
4. Loop:
   - `sqa-tool needs-review --count`. If zero, exit.
   - Tell the user the count.
   - Pull a batch of up to `max_agents` files via `--limit`.
   - Spawn one `review-file` subagent per file in parallel.
   - Wait for completion; continue.
5. Run `sqa-tool status` and report.

If the safety cap (50 batches) is hit, suggest `/loop /sqa-review`.

#### `sqa-resolve`

Two modes: `sqa-resolve auto` and `sqa-resolve interactive`.

**Phase 0 — Pre-resolve baseline check.** Runs the quality-check command
once to establish a clean baseline. The per-fix regression checks below
only have value if the project starts green.

**Phase 1 — Autonomous triage** (runs in both modes). Triage is
autonomous, not user-interactive — its purpose is to *offload* the user
so they only engage with the `interactive`-class set later.

- File-scoped untriaged findings: group by `file`, dispatch one
  `triage-file` subagent per file, in parallel batches.
- General (`file == null`) untriaged findings: dispatch a single
  `triage-general` subagent that handles the full set.

Parallel triage is **safe** because triage subagents only call
`sqa-tool triage` — they never edit source files. Defensive comments
(§ 6.4) come at resolve time, not triage time.

**Phase 2 — Resolve.**

For `auto`:
1. Serial `resolve-file` dispatch, one file at a time. Auto-resolve is
   the one phase that writes substantively to source code, and many real
   fixes span files; parallel `resolve-file` subagents can race or drift
   the patterns they're meant to follow.
2. After each `resolve-file`, run the quality-check command. If it
   fails, fix the regression before moving on — clean attribution
   requires the project to be green between files.
3. After all file-scoped resolves complete, run `resolve-general` once
   for any `auto`-class `file == null` findings. General findings often
   update docs that describe code; doing them last means the docs are
   written against the final state of the code.

For `interactive`: walks findings sequentially in-skill (not via
subagent). The user replies in natural language: "fix it," "skip,"
"show diff," "commit," "this is actually auto," etc. After every fix
that lands, the quality-check runs; regressions are addressed in the
same conversation.

#### `sqa-status`

Conversational wrapper around `sqa-tool status`. Reports counts and
breakdowns from the active result file (or a historical one via
`--from`). Useful for "what's the state of findings here?" and for
planning what to triage next.

### 6.2 Subagents

Each is a one-shot agent invoked by name from a user-facing skill. With
the exception of the `*-general` pair, all are scoped to a single file so
context-building costs are amortized across the work for that file.

- **`review-file`** — given a file path: reads `review-file-prompt.md`
  (the project's review guidance), calls `sqa-tool categories` to learn
  what tags to use, reads the file, calls `findings-for-file` to surface
  any multi-file findings other subagents have recorded in the same
  session, walks the prompt's concerns, records findings via
  `sqa-tool record-finding`, and calls `mark-reviewed` as the last step.
  Does not edit source files.

- **`triage-file`** — given a file path: reads `triage-guidelines.md`,
  classifies all untriaged findings on the file as `auto` / `interactive`
  / `ignore` via `sqa-tool triage`. When the appropriate resolution is
  "add a defensive comment near the relevant code," it triages `auto`
  and writes the comment-insertion instruction into the rationale. Does
  not edit source files.

- **`resolve-file`** — given a file path: reads all `auto`-class open
  findings whose `file` matches its assigned path or whose `related`
  contains it. For each finding, locates the affected code via
  `file` + `line` + `quoted_text`, applies the fix (and any defensive
  comment from the rationale), calls `sqa-tool resolve`. May edit related
  files for multi-file fixes — auto-resolve runs serially across files
  precisely so this is safe.

- **`triage-general`** — same job as `triage-file`, but operates on the
  set of `file == null` findings (project-wide concerns: missing docs,
  repo-level conventions, cross-cutting policies). Reads project-level
  docs the findings reference for context.

- **`resolve-general`** — applies fixes for all `auto`-class open
  `file == null` findings. Typically docs edits, README touches,
  module-docstring additions; occasionally a new markdown document for
  a genuinely cross-cutting policy that has no existing home.

### 6.3 Framework / project file split

The split is the answer to: "per-project skill installation lets each
project customize behavior, but tool upgrades need to refresh the
framework without clobbering customizations." Framework files in
`.claude/` are overwritten on `sqa-tool init`; project files are
preserved if they exist and created from defaults if they don't. Init
reports what was installed, overwritten, and preserved.

### 6.4 Defensive comments — the durable home for design intent

When a finding turns out *not* to need a behavior change but you want to
capture "we considered this and here's why we're leaving it":

- **Prefer triaging `auto`** with the fix being "add a clarifying comment
  near the relevant code." Write the comment-insertion instruction into
  the rationale; the resolver does the actual edit at resolve time. The
  comment becomes part of the source and is read naturally by every
  future reviewer (and every future maintainer).
- **`ignore` is for findings that should produce no code change at all**
  — genuinely wrong analyses, false positives in context, duplicates
  already covered by another finding.

Why prefer the comment? Source is the durable home for "why the code is
the way it is." Future review passes start from the current source — a
well-placed comment naturally guides the next reviewer, with no
metadata to keep in sync.

**Why this is safe to do at resolve time, not triage time.** Triage
subagents run in parallel and don't edit source files, which is what
makes parallel triage safe. The resolve phase is serial — one file at a
time — so it's safe to insert comments there. That's why the comment
instruction lives in the rationale: triage plans, resolve executes.

**Comment style:** length whatever the rationale needs (a sentence is
fine, a short paragraph is fine if needed); resolve confusion, don't
narrate development history; don't restate the code; place near the code
it explains; deduplicate against existing nearby comments. The full
guidance lives in `triage-guidelines.md`.

**Cross-cutting findings always have a home.** Project-wide concerns
(`file == null`) always land their rationale somewhere durable: the
canonical touchpoint (public API entry, central registry); a
module-level docstring or README; in rare cases, a new project-level
doc (`ARCHITECTURE.md`, `docs/conventions.md`). "The next reviewer will
just re-discover this" is not a valid resolution — every decision worth
keeping is worth giving a durable home.

## 7. Dispatch & parallelism

### 7.1 Skill-driven loop

Each user-facing skill drives its own loop until either the work is done
or a per-invocation safety cap is hit. The structure is intentionally
repetitive so the agent's reasoning load stays trivial:

1. Ask a tool for the count of remaining work
   (`needs-review --count`, etc.). If zero, exit.
2. Pull a batch of up to `max_agents` items via the tool's `--limit`.
3. Spawn subagents for the batch in parallel; **block until all
   complete** (task-completion-based, not polling).
4. Loop back to step 1, until done or cap.

Each iteration's context contribution is just compact tool outputs
(counts, brief summaries), so context grows slowly even across many
batches. Per-invocation safety cap (e.g. 50 batches) exists as a guard
against pathological cases.

The `hint:` lines on stderr from gate commands (§ 5.3) keep the loop
agent oriented even across many iterations.

### 7.2 Parallel for review and triage; serial for auto-resolve

The general rule is "parallelize phases that don't write to source code."
Review and triage don't write to source (they only mutate the result
file under fcntl lock), so they fan out per-file.

Auto-resolve writes to source. Many real fixes span files (DRY
extractions, renames, SSOT consolidations, following established
patterns); parallel `resolve-file` subagents can race on cross-file edits
or drift the very pattern they're meant to follow. Serial dispatch
preserves correctness at the cost of wall-clock time.

### 7.3 Cross-cutting general findings

Findings with `file == null` don't fit the per-file dispatch model. They
get one `triage-general` and one `resolve-general` subagent — both
operate on the full set of general findings at once. `resolve-general`
runs *after* all file-scoped resolves complete, so general findings
(typically docs) are written against the final state of the code, not a
moving target.

### 7.4 Per-invocation parameters

`max_agents` and the safety cap are per-invocation values, not config.
The skill prompts for `max_agents` at the start (with a sensible default,
typically 4) so the user can tune speed each time. The safety cap is
hard-coded in the skill markdown to a generous value users rarely hit.

## 8. Workflows

### 8.1 Initial setup

```bash
cd <project>                       # must be a git repo with at least one commit
sqa-tool init
$EDITOR .sqa/config.toml           # configure includes/excludes; optionally tweak categories
# Edit .claude/skills/sqa-review/project.md and .claude/skills/sqa-resolve/project.md
# to point at the project's quality-check command (e.g. ./runtools.sh).
```

`init` refuses to run if the directory isn't a git repository, or if the
repo has no commits yet — both cases produce an actionable error message
rather than silently creating broken state. After the pre-checks pass,
`init` scaffolds:

- `.sqa/` for project state (`config.toml`, `file_status.json`).
- `.claude/skills/<name>/SKILL.md` and `.claude/agents/<name>.md` for the
  user-facing skills and subagents (per-project copies, customizable).

`init` also warns about any artifacts from earlier versions of the tool
(`.sqa/findings/`, `.sqa.md` files, old agent filenames). It surfaces
them so the user can clean up at their own pace, but never touches them
automatically.

### 8.2 Review pass

User invokes `/sqa-review`. The skill drives its own loop (§ 6.1
`sqa-review`):

1. Read `project.md`; run the quality-check command; stop if it fails.
2. `sqa-tool start-result` — fresh session.
3. Pick `max_agents`.
4. Loop: count → batch → parallel `review-file` subagents → repeat.
5. Report via `sqa-tool status`.

A small follow-up review later, when only `src/auth/login.py` has
changed: the skill picks up only that file. The `review-file` subagent
reads the file, walks the project's review guidance, records new
findings via `sqa-tool record-finding` (with `--file`, `--line`,
`--quoted-text`, `--category`, optional `--related` for multi-file
concerns), and marks the file reviewed.

### 8.3 Resolve

User invokes `/sqa-resolve auto` or `/sqa-resolve interactive`. Phases 0,
1, 2 per § 6.1 `sqa-resolve`.

For `auto`: file-scoped resolves run serially (with quality-check after
each); then `resolve-general` runs once for any project-wide auto
findings.

For `interactive`: the skill walks the user through the
`interactive`-class findings sequentially, in natural-language
conversation per finding; quality-check runs after every fix that lands;
regressions are addressed in the same conversation before advancing.

The user never invokes triage as its own verb. To plan-without-fixing,
they use `/sqa-status`.

## 9. Multi-language support

The reviewer doesn't care what language the source files are in — it
reads, the prompt drives, the agent writes findings. There's no
per-language code path in the tool (no anchor comment table, no
language-specific parsers). Defensive comments are inserted in whatever
syntax the file uses; the agent reads the file and matches.

## 10. What we don't do

- **No persistent findings across sessions.** Each `/sqa-review`
  creates a fresh result file; findings recorded one session don't
  carry into the next. The substitute is defensive comments in source
  (§ 6.4) — design intent that's worth remembering goes in the code,
  where the next reviewer naturally reads it.
- **No in-source anchor comments.** Findings reference code by `file`
  + `line` + `quoted_text`, not by an inserted comment in the source.
- **No web UI or dashboard.** Findings are inspected via CLI, git, and
  the result-file JSON.
- **No cross-repo aggregation.**
- **No automated migration of state from earlier tool versions.** `init`
  warns about legacy artifacts but doesn't touch them.

## 11. Open questions / future directions

- **Cross-cutting auto-resolve dispatch.** Findings whose anchor spans
  multiple files are handled by dispatching to the `resolve-file`
  subagent for the primary file (with the `related` files in scope).
  This relies on the subagent doing the right thing across files; if it
  proves unreliable, a dedicated cross-cutting handler is a future
  addition.
- **Result-file retention.** Result files accumulate one-per-session.
  No built-in pruning; users gitignore them and clean up by hand. If
  disk usage becomes an issue, a `sqa-tool prune --older-than=30d` is
  the natural addition.
- **Per-aspect review subagents.** Currently one `review-file` subagent
  per file does all categories at once. A per-aspect fan-out (one
  Security agent across many files, etc.) might produce deeper findings
  per category at higher dispatch cost. Worth experimenting if review
  quality plateaus.
- **Persistent-finding opt-in.** If defensive comments turn out
  insufficient (specific failure mode: persistent "already-considered"
  findings get re-flagged every review and the re-triage cost genuinely
  hurts), a `--persistent` opt-in mode at init time could re-introduce
  per-finding records and in-source anchors. Not designed yet; deferred
  until real usage motivates it.

## Appendix: bundled defaults

Files installed by `sqa-tool init` (full paths under the project root):

```
.sqa/config.toml                                # files globs + categories
.sqa/file_status.json                           # empty; updated by mark-reviewed

.claude/skills/sqa-review/SKILL.md              # framework (overwritten)
.claude/skills/sqa-review/project.md            # project (preserved)
.claude/skills/sqa-resolve/SKILL.md             # framework
.claude/skills/sqa-resolve/project.md           # project
.claude/skills/sqa-status/SKILL.md              # framework only

.claude/agents/review-file.md                   # framework
.claude/agents/review-file-prompt.md            # project
.claude/agents/triage-file.md                   # framework
.claude/agents/triage-general.md                # framework
.claude/agents/triage-guidelines.md             # project
.claude/agents/resolve-file.md                  # framework
.claude/agents/resolve-general.md               # framework
```
