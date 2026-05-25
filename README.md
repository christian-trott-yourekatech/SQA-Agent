# sqa-tool

A code reviewer built on Claude Code skills and a small deterministic CLI.

The shape:

1. **Skills + deterministic tools.** The agentic surface is a small cluster of Claude Code skills (`/sqa-review`, `/sqa-resolve`, `/sqa-status`); load-bearing bookkeeping (change detection, finding storage, state-machine enforcement) lives behind the `sqa-tool` CLI.
2. **Per-run result files.** Each review session writes a single `.sqa/result_<timestamp>.json` containing every finding, triage decision, rationale, and status transition. No persistent finding store across sessions, no in-source anchor comments. Design intent that should outlive a single review is captured as **defensive comments in source**, written at resolve time.

See [`Docs/design.md`](./Docs/design.md) for the full design.

## Installation

Requires Python 3.12+, `git`, and [`uv`](https://docs.astral.sh/uv/).

```bash
curl -fsSL https://raw.githubusercontent.com/christian-trott-yourekatech/SQA-Agent/main/install.sh | bash
```

Or directly:

```bash
uv tool install git+https://github.com/christian-trott-yourekatech/SQA-Agent.git
```

This installs the `sqa-tool` CLI globally. To upgrade later, re-run either command (both use `--reinstall`).

To use the skills, you'll also need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated.

## Quickstart

From the root of any git repository:

```bash
sqa-tool init
```

This:
- Creates `.sqa/` (project state — `config.toml`, `file_status.json`, and result files once you start a session).
- Scaffolds `.claude/skills/sqa-{review,resolve,status}/SKILL.md` and `.claude/agents/{review-file,triage-file,resolve-file,triage-general,resolve-general}.md` so Claude Code finds them.
- Recommends gitignoring `.sqa/result*.json` and `.sqa/logs/` (result files quote source; the per-session audit value is lower than tracked files would warrant).
- Warns about any leftover artifacts from an earlier install of the tool (`.sqa/findings/`, `.sqa.md` files, old agent filenames) — it surfaces them so you can clean up at your own pace, but doesn't touch them automatically.

Then edit `.sqa/config.toml` to point at the files you want reviewed:

```toml
[files]
include = ["src/**/*.py"]
exclude = ["src/**/*_test.py"]

[categories]
# Defaults are reasonable; customize for your project's conventions.
list = ["dry-ssot", "interfaces", "logic", "comments", "error-handling", "kiss-yagni", "security", "project-specific"]
```

If your project has a quality-check command (`./runtools.sh`, `make check`, `npm test`), edit `.claude/skills/sqa-review/project.md` and `.claude/skills/sqa-resolve/project.md` to invoke it where indicated.

## Workflow

Inside a Claude Code session in the project:

| Slash command | What it does |
|---|---|
| `/sqa-review` | Run a review pass. Creates a fresh `.sqa/result_<timestamp>.json`, then dispatches one `review-file` subagent per file that has changed since last review. Findings are recorded to the result file. |
| `/sqa-resolve auto` | Autonomously triage any untriaged findings (parallel `triage-file` / `triage-general`), then auto-fix the `auto`-class ones (serial `resolve-file`, then `resolve-general` last). |
| `/sqa-resolve interactive` | Triage as above, then walk the `interactive`-class set with the user, fixing each in a multi-turn conversation. |
| `/sqa-status` | Report counts and breakdowns of findings from the active result file. |

For very large repos or quota-paced execution, wrap with `/loop`:

```
/loop /sqa-review
/loop 1h /sqa-resolve auto
```

## CLI reference

The `sqa-tool` CLI is the deterministic backend the skills call. You can also use it directly.

```
# Session lifecycle
sqa-tool init                                         # Scaffold .sqa/ and .claude/
sqa-tool start-result                                 # Begin a review session (prints path + categories)
sqa-tool active-result                                # Print path of most-recent result file
sqa-tool categories                                   # Print configured category list

# Change detection
sqa-tool needs-review [--count] [--limit N]           # List/count files needing review
sqa-tool mark-reviewed <path>                         # Record current blob hash
sqa-tool diff-since-review <path>                     # Diff vs last-reviewed blob

# Findings (operate on the active result by default; --from <file> reads a historical one)
sqa-tool record-finding --message=... --severity=... \
    --file=<path> [--line=N] [--quoted-text=...] \
    [--category=...] [--related=<path> ...] [--rationale=...]
sqa-tool triage <id> auto|interactive|ignore --rationale=...
sqa-tool resolve <id> --rationale=...
sqa-tool show-finding <id>                            # Print one finding as JSON
sqa-tool list-findings [--triage=...] [--status=...] [--count] [--limit N] [--from <path>]
sqa-tool findings-for-file <path> [--from <path>]
sqa-tool status [--from <path>]                       # Counts and breakdowns
```

Run `sqa-tool <command> --help` for full options.

### Finding state machine

Every finding has a `triage` decision and a `status`:

| triage / status | meaning |
|---|---|
| `null` + `open` | freshly recorded, not yet triaged |
| `auto` + `open` | pending autonomous fix |
| `interactive` + `open` | pending discussion with the user |
| `ignore` + `resolved` | bookkeeping close, no code change |
| `auto` + `resolved` | fixed by `resolve-file` / `resolve-general` |
| `interactive` + `resolved` | fixed during the interactive walk |

Key transitions:
- `sqa-tool triage <id> ignore` flips `status` to `resolved` in the same call (ignore is a terminal close).
- Re-triaging an `ignore + resolved` finding to `auto` / `interactive` flips status back to `open` — un-ignoring is permitted.
- Re-triaging a finding that's already been *action*-resolved (auto/interactive + resolved) is **rejected** — no reopen. Re-surfacing the concern means recording a fresh finding on the next review.

### Result files

Each `/sqa-review` invocation creates one `.sqa/result_<timestamp>.json`. The file is the audit record for that session: findings recorded by the review, decisions made by triage, rationales added by resolve, status transitions. Nothing is deleted — `resolve` flips `status`; the entry stays for the record.

The "active" result file is the most recent one. Mutating commands (`record-finding`, `triage`, `resolve`) operate on it; read commands default to it but accept `--from <path>` to inspect an older session (historical results are **read-only**).

`record-finding` enforces a safety guard: once any finding in the active result has been resolved, new findings can't be appended without `--force`. This catches the "I forgot to `start-result` between sessions" mistake.

## Storage

```
.sqa/
  config.toml                    # include/exclude globs + category list
  file_status.json               # last-reviewed blob hash per file (fcntl-locked)
  result_<timestamp>.json        # one per /sqa-review session
  logs/                          # optional, gitignored
```

Result files are recommended for `.gitignore` by default; track them deliberately if you want a git-versioned history of reviews.

## Defensive comments — the durable home for design intent

When a finding turns out not to need a behavior change but you do want to record "we considered this and here's why we're leaving it," **prefer triaging `auto` with the resolution being "add a clarifying comment near the relevant code."** The next reviewer reads the comment naturally — no metadata to keep in sync, no anchor IDs in source. `ignore` is reserved for findings that should produce no code change at all (false positives, factually wrong analyses, duplicates).

The triage guidelines in `.claude/agents/triage-guidelines.md` cover comment style (length appropriate to the rationale; resolve confusion, don't narrate development history; place near the code it explains). See [`Docs/design.md`](./Docs/design.md) § 6.4 for the full rationale.

## Development

```bash
git clone https://github.com/christian-trott-yourekatech/SQA-Agent
cd SQA-Agent
uv sync --group dev
./runtools.sh              # format, lint, type-check, test
```

## License

MIT — see [LICENSE](./LICENSE).
