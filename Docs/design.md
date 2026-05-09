# Reviewer v2 — Design

A redesign of the SQA Agent reviewer (v1 lives at `../Reviewer/`). Two structural shifts from v1:

1. **Findings persist across runs** as first-class records, anchored in source by short comment tags. No more "every run starts cold and rediscovers everything."
2. **Skills + deterministic tools** replace the Python-SDK-based harness. The agentic surface is a small cluster of skills; load-bearing bookkeeping (change detection, finding storage, schema enforcement) lives behind a small CLI tool.

This document describes the design; implementation is out of scope here.

---

## 1. Motivation

Problems with v1:

- Each `review` produces a fresh `result_<timestamp>.json` from nothing. Triage decisions don't carry forward; the same finding is re-discovered and re-triaged on every run.
- File-blob hash gates re-review, so any unrelated edit to a file resurfaces every prior finding.
- The agent has no awareness of past findings during a review — it cannot know "this was considered and accepted" or "this was fixed."
- Orchestration is bound to `claude_agent_sdk`. The user can't easily switch models or harnesses, and updating workflow behavior requires Python edits.

v2 fixes both classes of problem.

## 2. Goals & non-goals

### Goals

- Findings are durable. Triage decisions outlive the run that produced them.
- The agent has structured awareness of prior findings during review and respects them.
- Anchors travel with code (renames, moves, refactors) without manual sync.
- Bookkeeping is deterministic and testable; judgment is agentic.
- Skill-driven UX, harness-native (no SDK lock-in).
- Scales to projects with hundreds of files and thousands of findings.

### Non-goals

- Cross-repo finding aggregation.
- An OSS-grade UI / dashboard. Findings are inspected via CLI and `git`.
- Direct migration of v1 result files. v2 starts fresh; v1 stays available for projects already using it.

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
│   review-file   — review one file with prior-finding context   │
│   triage-file   — autonomously triage untriaged findings in    │
│                   one file                                     │
│   resolve-file  — fix all auto-class findings in one file      │
│   fix-orphans   — clean up orphans the tool can't fix          │
└────────────────────────────────────────────────────────────────┘
                          │
                          │ all state changes
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ sqa-tool (deterministic CLI)                                │
│   needs-review, mark-reviewed,                                 │
│   findings-for-file, list-findings, show-finding, status,      │
│   record-finding, triage, resolve, reopen,                     │
│   orphans, gc, diff-since-review                               │
└────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌────────────────────────────────────────────────────────────────┐
│ On-disk state                                                  │
│   .sqa/                                                     │
│     config.toml             — include/exclude globs            │
│     file_status.json        — per-file last-reviewed git hash  │
│                               (fcntl-locked for concurrent     │
│                                writes)                         │
│     findings/<id>.json      — one file per finding             │
│   <project tree>                                               │
│     .sqa.md              — top-level (project) scope anchors│
│     <dir>/.sqa.md        — directory (module) scope anchors │
│     <source files>          — file-scope anchors as comments   │
└────────────────────────────────────────────────────────────────┘
```

The tool owns *state*. Skills and subagents own *judgment*. They never edit state files directly — always via `sqa-tool`.

## 4. Storage model

### 4.1 Anchors

A finding has one or more **anchors** — short comments embedded in source files (or `.sqa.md` files) that tag the finding's location.

Format:

```
# sqa: K7M3X, A4B9P
```

IDs are short random base32 strings (5 characters, ~25 bits of entropy). They are short enough to type, speak, and grep; the collision probability for any realistic project size is negligible. The tool generates a fresh ID on `record-finding` and retries on the rare file-exists collision.

Per language:

| Language | Comment prefix | Example |
|---|---|---|
| Python, shell, Ruby | `#` | `# sqa: K7M3X` |
| JavaScript, TypeScript, Go, Rust, C, C++ | `//` | `// sqa: K7M3X` |
| HTML, XML | `<!-- ... -->` | `<!-- sqa: K7M3X -->` |
| SQL | `--` | `-- sqa: K7M3X` |
| CSS | `/* ... */` | `/* sqa: K7M3X */` |
| YAML, TOML, INI | `#` | `# sqa: K7M3X` |
| Markdown | `<!-- ... -->` | `<!-- sqa: K7M3X -->` |

Multiple findings can share a line: `# sqa: K7M3X, A4B9P, Q2R7T`.

The comment may appear on its own line or trailing a code line. The exact line number is **not** stored — the tool finds anchors by grepping.

### 4.2 Anchor location *is* the scope

A single rule governs scope:

> A `.sqa.md` file in a directory scopes its findings to that directory and its descendants. A finding's scope is wherever its anchor lives.

This means:

- File scope: anchor in the source file itself.
- Module scope: anchor in `<dir>/.sqa.md`.
- Project scope: anchor in the top-level `.sqa.md` (the project root is just the topmost directory).

There is no special-case handling for project vs. module scope — it's the same rule applied at a different directory.

The finding JSON file does **not** store a scope field. Scope is derived from where the anchor for ID *X* currently lives. This makes renames and directory moves automatic: `git mv auth/ identity/` carries the metadata file and all anchors with it.

### 4.3 `.sqa.md` files

`.sqa.md` is anchors-only. It does **not** quote finding text or its own location — both would create sync footguns when the JSON content or the directory name changes.

A typical file looks like:

```markdown
<!-- sqa: K7M3X, A4B9P -->

<!-- sqa: Q2R7T -->
```

That's it. Optional human-authored prose (notes, headings) is fine — the tool only cares about lines containing anchors. Grouping multiple anchors on one line is a stylistic choice; ordering and spacing are entirely up to the user.

The file is git-mergeable in the normal way and travels with `git mv`.

`.sqa.md` is created lazily — only when a finding requires it. Empty or anchor-less metadata files are pruned by `sqa-tool orphans`.

### 4.4 Finding JSON files

One file per finding at `.sqa/findings/<id>.json`. **The filename is the ID; the JSON content does not repeat it.** This avoids any chance of filename/content drift.

```json
{
  "message": "Session-creation path raises bare Exception; rest of the module uses AuthError. Standardize on AuthError.",
  "severity": "warning",
  "triage": "interactive",
  "status": "open",
  "rationale": "Standardizing on AuthError lets callers handle auth failures uniformly. Marc has flagged this as a customer-visible bug source.",
  "related_files": ["auth/login.py", "auth/session.py"]
}
```

Field reference:

| Field | Type | Description |
|---|---|---|
| `message` | string | The finding itself. Plain prose. |
| `severity` | enum: `info \| warning \| error` | |
| `triage` | enum: `auto \| interactive \| ignore` or `null` | `null` means untriaged. |
| `status` | enum: `open \| resolved` | |
| `rationale` | string | Current-state reasoning. Updated on every state change; the LLM is responsible for keeping it coherent. **Not** a history log. |
| `related_files` | string[] | Files the finding refers to. Paths are project-relative (the same convention as `git ls-files` output). Used by `findings-for-file` to surface higher-scope findings to file reviews, and by `orphans` to detect when referenced files have been renamed/deleted. |

**No `id` field, no `history` field, no `line` field, no `scope` field.** ID is the filename. History comes from `git log .sqa/findings/<id>.json`. Line is found by grepping anchors. Scope is derived from anchor location.

ID format: 5-character base32 (alphabet `A-Z2-7`, excluding ambiguous characters where reasonable). Generated randomly by `record-finding`; on collision (file already exists) the tool retries.

### 4.5 Files without comment syntax

JSON, binary, and some config formats can't carry inline anchors. Findings on these files are anchored in the **nearest enclosing `.sqa.md`** (e.g. for `data/config.json`, the anchor lands in `data/.sqa.md` or, if that doesn't exist yet, the project-root `.sqa.md`). The actual file path goes in `related_files`.

This treats them uniformly with module-scope findings — same scope rule, same renaming behavior, no special path-string fragility. The only loss is that the finding's anchor isn't *immediately* visible when reading the file itself, which is intrinsic to non-commentable files.

### 4.6 Security & data-leakage tradeoff

Storing findings in-tree means:

- Finding text is committed to git history. Resolved findings whose JSON files are deleted still appear in older commits.
- Security findings, which may name vulnerable code paths, become permanently visible in repo history. Even after the underlying issue is fixed, the description remains discoverable.
- For private repos this is mostly acceptable; for public repos or repos shared with vendors, it's a real concern.

**Default: do not gitignore `.sqa/`.** The version-controlled audit trail is the primary value proposition. `sqa-tool init` logs an explicit message to the user noting:

- That `.sqa/findings/` will be tracked by git unless they choose otherwise;
- That for security-sensitive projects (or projects shared with parties who shouldn't see vulnerability descriptions), they may want to add `.sqa/findings/` to `.gitignore`;
- That the consequence of gitignoring is loss of the git-based audit trail and merge-friendly storage.

Future enhancements (post-MVP, only if real usage demands it):

- A `--private` flag on `record-finding` that routes a single finding to `.sqa/private/findings/<id>.json` (gitignored by `init`).
- A `private_severities` config knob that auto-routes findings of given severities to the private location.

These are deferred — the simple "all in or all out, your call" default is enough to start.

## 5. Skills and subagents

### 5.1 User-facing skills

Three skills, each owning one user-visible verb. Composable; user-invokable independently. The `sqa-` prefix avoids collision with Claude Code's built-in `/review` slash command.

**Installation model:** skills and subagents are installed per-project, scaffolded by `sqa-tool init` into the project's harness skill/agent directories. This lets each project customize the skill markdown directly — review prompts, the project-local quality-check command, and any other project-specific guidance live in the project's copy. The cost is a slight version-skew risk if the central skill bundle gains improvements after a project initializes; this is acceptable for now and revisitable.

#### `sqa-review` skill

The skill drives a self-paced loop until the work is done (or a safety cap is hit — see [§ 6](#6-dispatch--parallelism)). One invocation handles a complete review under normal circumstances.

Per invocation, the skill:

1. Runs `sqa-tool orphans` (which auto-fixes the deterministic class). If any orphans remain, dispatches a `fix-orphans` subagent before proceeding.
2. Loops:
   - Asks `sqa-tool needs-review --count`. If zero, exit loop.
   - Pulls a batch of up to *max_agents* files via `sqa-tool needs-review --limit=<max_agents>`.
   - Spawns `review-file` subagents in parallel.
   - Continues until either `needs-review --count` is zero or the per-invocation safety cap is hit.
3. Optionally runs a project-local quality-check command (e.g. `./runtools.sh`, `make check`, `npm test`). The command is encoded directly in the project's copy of the skill markdown; each project edits its skill to point at whatever check it actually uses.
4. Prints summary by calling `sqa-tool status`.

If the safety cap is hit before completion, the skill exits with a message suggesting `/loop /sqa-review` for continuation.

#### `sqa-resolve` skill

Combines autonomous triage with resolution. Replaces v1's separate triage and resolve commands as a user-facing flow.

Two modes: `sqa-resolve auto` and `sqa-resolve interactive`. Each runs a self-paced loop, same pattern as `sqa-review`.

Per invocation:

1. **Autonomous triage of untriaged findings.** Group untriaged findings by anchor file; dispatch `triage-file` subagents in parallel batches. Each subagent classifies all untriaged findings in its file as `auto` / `interactive` / `ignore`. Difficult calls land as `interactive`, which is the design — the user only engages with the curated `interactive` set later.
2. **Resolve the requested class:**
   - **Auto-resolve** — group `auto`-class open findings by anchor file; dispatch `resolve-file` subagents in parallel batches. Each subagent reads its file once, applies all relevant fixes, calls `sqa-tool resolve` per finding. After fixes, optionally runs the project-local quality-check command (encoded in the skill markdown).
   - **Interactive-resolve** — walks `interactive`-class findings sequentially with the user, multi-turn conversation per finding, in-skill. Slash commands roughly mirror v1 (`/resolve`, `/skip`, `/quit`, `/diff`). This is the user-engagement endpoint of the workflow — everything before this is autonomous.

The user never invokes triage as its own verb. A user who wants to plan-without-fixing inspects state via the `sqa-status` skill.

State changes go through `sqa-tool triage` / `resolve` / `reopen`.

#### `sqa-status` skill

Conversational wrapper around `sqa-tool status`. Reports counts (new, untriaged, auto, interactive, ignored, resolved-recently) and breakdowns (by directory, by severity). Useful for "what's the state of findings here?" questions and for planning what to triage next.

### 5.2 Subagents

Defined formally as markdown in the project's harness `agents/` directory (scaffolded by `init`). Each is a one-shot agent invoked by name from the user-facing skills. Subagent markdown carries the prompt content directly — including the review-prompt sections that the `review-file` subagent walks. With the exception of `fix-orphans`, all are scoped to a single file so context-building costs are amortized across the work for that file.

- **`review-file`** — given a file path, performs a full review. Calls `findings-for-file` to load prior context, reads the file, walks the review-prompt sections embedded in its own markdown, records new findings, refreshes/closes/reopens prior findings as warranted, and calls `mark-reviewed` on completion. Biases toward conservative judgment ("if uncertain about staleness, keep the finding open"). Also biases toward narrow scope: anchor findings at file scope unless they're genuinely cross-cutting (not addressable by editing one file). This avoids flooding project `.sqa.md` with concerns that really belong with one file, and reduces lock contention on shared `.sqa.md` files.
- **`triage-file`** — given a file path, autonomously classifies all untriaged findings anchored in that file (or its `.sqa.md`) as `auto` / `interactive` / `ignore`. Routes ambiguous or judgment-heavy findings to `interactive` rather than guessing.
- **`resolve-file`** — given a file path, applies fixes for every auto-class finding anchored in that file. Reads the file once; resolves all relevant findings; calls `sqa-tool resolve` per finding. Used only by `resolve auto`.
- **`fix-orphans`** — handles the orphan classes the tool can't fix deterministically (anchors with no JSON, JSONs with no anchors, `related_files` referencing nonexistent paths). One-shot, no per-file scope; orphans are usually few.

A subagent never edits finding JSON directly — only via `sqa-tool` calls.

For source files, subagents Edit directly to insert anchors at the LLM-chosen location near the relevant code (no contention: each source file is touched by only one subagent at a time).

For `.sqa.md` files (project- or module-scope anchors), subagents pass `--anchor=<file>.sqa.md` to `record-finding`, which inserts the anchor under `fcntl` lock — avoiding races when parallel subagents both want to add anchors to the same shared file.

Cross-cutting findings (anchors in multiple files) are an open question — for now they're handled by dispatching the resolve to the file containing the first anchor; the subagent is expected to address all relevant files. If this proves unreliable, a dedicated handler is a future addition.

### 5.3 Known tradeoff: section-at-a-time conversational depth

In v1, each per-file review section is a separate conversational turn within a stateful `ClaudeSDKClient`. This gets both prompt caching (file already in context) *and* the focusing benefit of "answer this one question now."

Subagents are one-shot invocations; we can't replicate the per-section conversational structure. The `review-file` subagent's single prompt instructs it to walk each section sequentially with dedicated attention to each. The agent stays in one context (caching preserved), but the per-section focus comes from prompt structure rather than from the conversation pattern.

This is likely a quality regression compared to v1, though probably small. We'll accept it for v2 and revisit if measurable. The mitigations available if it matters:

- Tune section prompts to reinforce sequential, focused processing.
- Reintroduce a thin SDK-backed `sqa-tool review-file` subcommand that internally uses a stateful session — localized SDK dependency, preserves the v1 conversational pattern.

The saving grace is durability: repeated reviews accumulate findings over time, so a single review's slightly-shallower depth matters less than v1's "every run rediscovers everything."

## 6. Dispatch & parallelism

### 6.1 Skill-driven loop

Each user-facing skill drives its own loop until either the work is done or a per-invocation safety cap is hit. The structure is intentionally repetitive so the agent's reasoning load stays trivial:

1. Ask a tool for the count of remaining work (`needs-review --count`, etc.). If zero, exit.
2. Pull a batch of up to *max_agents* items via the tool's `--limit` flag.
3. Spawn subagents for the batch in parallel; **block until all complete** (task-completion-based, not polling).
4. Loop back to step 1, until done or cap.

Each iteration's context contribution is just compact tool outputs (counts, brief summaries), so context grows slowly even across many batches. Per-invocation safety cap (e.g. 50 batches) exists as a guard against pathological cases — most invocations never hit it.

State in `.sqa/` carries between invocations, so a capped exit is always recoverable.

**Slowest-agent-bound batches.** Each batch's wall time is determined by its slowest member — a fast subagent that finishes early sits idle while the rest of the batch completes. v1's `asyncio.Queue`-based dispatch avoided this by letting workers pull on demand, but that pattern doesn't translate cleanly to prose-driven dispatch in a skill. The harness's `run_in_background` option could in principle approximate the queue model, but the bookkeeping (track in-flight agents, dispatch a replacement on each completion) is exactly the kind of state-tracking that prose-driven control isn't reliable at. For v2 we accept the slowest-bound dynamic and let users overprovision *max_agents* to compensate — running with concurrency 8 instead of 4 amortizes a single slow file across more parallel work.

**Why the loop body isn't itself a subagent.** The review skill's own context grows by only a few KB per iteration (compact tool outputs, brief subagent summaries), so even 50 iterations stays well under any context limit. The inner-loop reasoning ("count > 0? dispatch batch.") is trivially repetitive. Wrapping the loop body in another subagent would add an indirection without solving a real problem; if reliability ever becomes an issue at very large scale, the safety-cap + `/loop` mechanism is the right escape hatch.

### 6.2 Pacing for quota concerns (optional)

For users who want to throttle for quota or time-budget reasons, `/loop` wraps the skill:

```
/loop 1h /sqa-review        # paced for quota recovery
```

This is *optional*. The skill works fine without it; pacing is purely a user preference for slow-roll execution.

### 6.3 Per-invocation parameters

`max_agents` and the safety cap are *per-invocation* values, not config. The skill prompts for `max_agents` at the start (with a sensible default) so the user can tune speed each time. The safety cap is hard-coded in the skill markdown to a generous value users rarely hit.

These don't appear in `.sqa/config.toml`.

### 6.4 Concurrency-safe state writes

Multiple subagents run in parallel and may all call `sqa-tool mark-reviewed` (and other state-mutating commands) concurrently. The tool guarantees safety:

- **`file_status.json`** — single file, easy to inspect or hand-edit. Updates are protected by an `fcntl` exclusive lock held for the read-modify-write critical section. Lock contention is negligible because the section is short (kilobytes, not megabytes).
- **Per-finding JSON files** — concurrent `record-finding` calls allocate distinct random IDs, so no shared file is contended.
- **Source-file anchor edits** — partitioned by file: a given source file is only touched by one subagent at a time (its assigned reviewer/resolver).
- **`.sqa.md` edits** — could in principle be touched by multiple subagents (e.g., two parallel `triage-file` subagents both updating findings in `auth/.sqa.md`). Tool serializes these via `fcntl` lock as well.

Linux/Mac/WSL only for now — `fcntl` works on all three. Windows-native support is out of scope.

## 7. Deterministic tool (`sqa-tool`)

A small Python CLI program. Per-finding JSON files don't need a database driver, but Python is still the most ergonomic choice for the orchestration logic — git interaction, schema enforcement, glob matching, anchor regex per language. Bash is used only where it's genuinely cleaner (e.g., wrapping `git hash-object --stdin-paths`).

### 7.1 Subcommand reference

```
sqa-tool init
    Create .sqa/ with default config.toml, empty findings/ dir, and
    empty file_status.json. Scaffold the project's harness skill and
    agent directories with the sqa-review / sqa-resolve / sqa-status
    skills and the review-file / triage-file / resolve-file /
    fix-orphans subagents (each carrying its own prompt content
    inline). Log an informational message about whether to gitignore
    .sqa/findings/ for security-sensitive projects (see § 4.6).

sqa-tool needs-review [--count] [--limit N]
    List files (from configured includes/excludes ∩ git-tracked files)
    whose current blob hash differs from the recorded last-reviewed
    hash. Prints one path per line.
    --count   Print just the integer count (for skill-loop guards).
    --limit N Print at most N entries (for batch dispatch).

sqa-tool mark-reviewed <path>
    Record the file's current blob hash as last-reviewed (updates
    file_status.json under fcntl lock). Safe for concurrent callers.

sqa-tool findings-for-file <path>
    Print findings whose anchor is in <path> OR whose anchor is in any
    ancestor .sqa.md AND whose related_files matches <path> (literal
    or glob). JSON array on stdout. Used by review subagents.

sqa-tool list-findings [path] [-r] [--triage=...] [--status=...] \
                           [--count] [--limit N]
    Browse / query. Path optional; -r for recursive descent. Filters
    optional. JSON array on stdout (or count integer with --count).
    --count   Print just the integer count.
    --limit N Print at most N findings.

sqa-tool show-finding <id>
    Pretty-printed single finding.

sqa-tool status [path]
    Report counts (untriaged, auto, interactive, ignored, resolved)
    and breakdowns (by directory, by severity). Path scopes the report
    to a subtree. Backs the `status` skill and is also useful directly.

sqa-tool record-finding \
    --message=<text> --severity=<info|warning|error> \
    [--anchor=<file>] [--related=<file>...] [--rationale=<text>]
    Allocate a fresh ID and write the JSON file. Prints the new ID
    on stdout.

    --anchor (optional): if provided, the tool inserts the anchor
    comment into the named file under fcntl lock. Use this for any
    SHARED file (project or module .sqa.md) where parallel
    subagents may contend for writes. The tool picks the comment
    syntax for the file's language.

    --anchor omitted: the caller (LLM) is responsible for inserting
    `# sqa: <id>` (or per-language equivalent) into the source file
    via Edit, near the relevant code. Use this for source files where
    the LLM has location-choice judgment and there's no contention
    (each source file is touched by only one subagent at a time).

    For un-commentable files (JSON, binary, etc.), pass
    --anchor=<dir>/.sqa.md (the nearest enclosing) and list the
    actual file path in --related.

    --related captures the files the finding is ABOUT. Used by
    findings-for-file (to surface higher-scope findings to file
    reviews) and orphans (to detect stale references after renames).

    Findings whose anchors are not actually inserted are flagged by
    `orphans` on the next review.

sqa-tool triage <id> auto|interactive|ignore --rationale=<text>
sqa-tool resolve <id> --rationale=<text>
sqa-tool reopen <id> --rationale=<text>
    State transitions. Each writes the finding JSON; the rationale is
    fully replaced (the LLM is responsible for coherent prose).
    "resolve" also removes the anchors from source.

sqa-tool orphans
    Detects rot in finding/anchor consistency. Some classes are fixed
    deterministically by the tool itself; others are reported for
    human/LLM judgment.

    Auto-fixed:
      - Empty .sqa.md files → deleted.
      - Source-file anchor whose file isn't in related_files
        → file added to related_files.

    Reported (require judgment):
      - Findings whose ID has no anchor anywhere.
      - Anchors in source/.sqa.md whose ID has no JSON file.
      - Findings whose related_files contains nonexistent paths.

    Run implicitly at the start of each review session.

sqa-tool gc [--older-than=<duration>]
    Prune resolved finding JSON files. Default keeps everything; with
    --older-than (e.g. 30d), only resolved findings whose JSON file
    hasn't been modified within the window are deleted.

sqa-tool diff-since-review <path>
    Print git diff of <path> against its last-reviewed blob. Used by
    review subagents that want diff-scoped review.
```

### 7.2 Config file (`.sqa/config.toml`)

```toml
[files]
include = ["src/**/*.py"]
exclude = ["src/**/*_test.py"]
```

That's it. No `[agent]` block (model selection is harness-native), no `[tools]` block (skills invoke project-local checks directly via Bash), no `[dispatch]` block (per-invocation parameters come from skill arguments or interactive prompts; see [§ 6.3](#63-per-invocation-parameters)).

## 8. Workflows

### 8.1 Initial setup

```bash
cd <project>
sqa-tool init
$EDITOR .sqa/config.toml          # configure includes/excludes
# Edit the project's copy of sqa-review / sqa-resolve skill markdown
# to point at the project's quality-check command (e.g. ./runtools.sh).
# init logs a note about gitignoring .sqa/findings/ if appropriate.
```

`init` scaffolds skills and subagents into the project's harness directories. They are project-local copies — each project owns and customizes them.

### 8.2 Routine review

User invokes the `sqa-review` skill. The skill drives its own loop:

1. Runs `sqa-tool orphans` (auto-fixes deterministic class). Dispatches `fix-orphans` subagent if any remain.
2. Loops: fetches a batch of up to *max_agents* files via `needs-review --limit`, dispatches `review-file` subagents in parallel, repeats until `needs-review --count` returns zero (or safety cap is hit).
3. Optionally runs the project-local quality-check command (encoded in the skill markdown).
4. Reports summary via `sqa-tool status`.

Under normal circumstances, one invocation handles a complete review. The user wraps with `/loop /sqa-review` only if they want quota pacing.

A small follow-up review a day later, when only `auth/login.py` has changed: the skill picks up only that file. The subagent loads prior findings (file-scope from the file itself, plus module-scope from `auth/.sqa.md` whose `related_files` matches `auth/login.py`, plus project-scope likewise). It re-evaluates each, refreshes rationale where needed, records new findings if any, and marks the file reviewed.

### 8.3 Resolve

User invokes `sqa-resolve auto` or `sqa-resolve interactive`. The skill autonomously triages any untriaged findings first (via `triage-file` subagents), then resolves the requested triage class — auto-class via `resolve-file` subagents, interactive-class via in-skill conversation with the user.

### 8.4 Branch divergence on finding IDs

With random base32 IDs, the collision probability across branches is negligible for any realistic project size (5-character base32 = ~33M possible IDs; for a project with 1000 findings, the probability of any cross-branch collision is on the order of 0.001%). Two branches creating findings in parallel should merge without conflict.

If a collision does occur, it manifests as a normal git conflict on `<id>.json` and is resolved by deleting one of the colliding files, re-running `record-finding` to get a fresh ID, and updating the anchor comment. A `sqa-tool reconcile` subcommand for automated handling is deferred until this becomes painful in practice.

### 8.5 Refactors and renames

| Action | Behavior |
|---|---|
| `git mv foo.py bar.py` | File-scope anchors travel with content. No tool action needed. |
| `git mv auth/ identity/` | `identity/.sqa.md` and all anchors travel together. `related_files` containing `auth/...` becomes stale; `orphans` flags it; LLM updates on next review. |
| Delete `foo.py` | Anchors vanish. `orphans` reports the orphaned findings; user or LLM closes them or relocates. |
| Refactor splits a directory | LLM-assisted: surface `.sqa.md` to the user; they decide which findings move where. |

## 9. Multi-language support

The per-language comment table in [§ 4.1](#41-anchors) is canonical. The tool consults it in two places:

- `record-finding`: pick the right comment syntax to insert.
- `orphans` and `findings-for-file`: pick the right regex for grep.

New languages are added by extending the table — no code beyond a config map.

## 10. Open questions

These are deliberately deferred; first implementation can pick reasonable defaults and revisit.

- **Cross-cutting findings and `related_files` globs.** Should we allow patterns like `**/*.py`, or require explicit file lists? Globs are more powerful but harder to reason about. Start with explicit lists; add globs if needed.
- **Cross-cutting auto-resolve.** Findings whose anchor spans multiple files are dispatched (today) to a `resolve-file` subagent for one of those files, which is expected to address all relevant files. If this proves unreliable, a dedicated cross-cutting handler is a future addition.
- **Diff-scoped review prompts.** Should we ship a default review prompt that runs only against `diff-since-review`, in addition to whole-file? Deferred until we see how often it's wanted.
- **`reconcile` subcommand for ID collisions.** Deferred; collisions should be vanishingly rare with random IDs.
- **`--private` finding flag and severity-routed private storage.** Deferred until real users surface the need.
- **Section-at-a-time review quality.** May need measurement once we have v2 running side-by-side with v1. If quality regression is meaningful, the SDK-backed escape hatch in [§ 5.3](#53-known-tradeoff-section-at-a-time-conversational-depth) is available.
- **Skill prompts.** The actual content of the review/resolve/status skill markdown is left to implementation. The interfaces above (which tools they call, what state they touch) constrain the prompts adequately.

## 11. Out of scope for v2

- A web UI / dashboard.
- Cross-repo aggregation.
- Migration from v1 result files. Projects that use v1 keep v1; new projects use v2.
- Model-selection or thinking-budget configuration inside `.sqa/config.toml`. These come from the harness.

---

## Appendix: comparison to v1

| Concern | v1 | v2 |
|---|---|---|
| Finding persistence | Per-run `result_<ts>.json`; lost on next run | Per-finding `.sqa/findings/<id>.json`; durable |
| Anchoring | None | `# sqa: <id>` comments + `.sqa.md` for higher scopes |
| Triage memory | Lost on next review | Carried forward; LLM sees prior findings during review |
| Re-review trigger | File blob changed | Same; but anchors prevent re-rediscovery |
| Orchestration | Python harness on Claude Agent SDK | Skills + small CLI; harness-native |
| Model selection | `[agent]` config block | Harness-native |
| User-facing verbs | `review`, `triage`, `resolve` | `sqa-review`, `sqa-resolve`, `sqa-status` |
| Per-file review structure | One stateful SDK session, section-per-turn | One subagent invocation, sections walked in-prompt |
| Parallelism | SDK-level `asyncio.gather` over a queue | Skill-driven subagent fan-out, bounded |
| Large-repo pacing | All-in-one invocation | Cron/loop wrapper of bounded invocations |
| Storage of finding text | In-repo (single result file) | In-repo (per-finding JSON), tracked by default |
| History/audit | Ad-hoc | `git log` on the finding JSON |
| Finding IDs | Sequential ints (per-run) | Short random base32 (5 chars), durable, branch-safe |
