# Reviewer v2 (sqa-tool)

A code reviewer built on Claude Code skills and a small deterministic CLI, with **persistent findings** anchored in source by short comment tags.

The two structural shifts from [v1](https://github.com/christian-trott-yourekatech/Reviewer):

1. **Findings persist across runs.** Each finding is a small JSON file under `.sqa/findings/`, anchored in source by a short comment like `# sqa: K7M3X`. Triage decisions and resolution rationale carry forward — the same issue isn't rediscovered and re-triaged on every review.
2. **Skills + deterministic tools** replace the v1 Python-SDK harness. The agentic surface is a small cluster of Claude Code skills (`/sqa-review`, `/sqa-resolve`, `/sqa-status`); load-bearing bookkeeping (change detection, finding storage, schema enforcement) lives behind the `sqa-tool` CLI.

See [`Docs/design.md`](./Docs/design.md) for the full design rationale.

## Installation

Requires Python 3.12+, `git`, and [`uv`](https://docs.astral.sh/uv/).

```bash
curl -fsSL https://raw.githubusercontent.com/christian-trott-yourekatech/Reviewer2/main/install.sh | bash
```

Or directly:

```bash
uv tool install git+https://github.com/christian-trott-yourekatech/Reviewer2.git
```

This installs the `sqa-tool` CLI globally. To upgrade later, re-run either command (both use `--reinstall`).

To use the skills, you'll also need [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated.

## Quickstart

From the root of any git repository:

```bash
sqa-tool init
```

This:
- Creates `.sqa/` (project state — config, findings, file-status hashes).
- Scaffolds `.claude/skills/sqa-{review,resolve,status}.md` and `.claude/agents/{review-file,triage-file,resolve-file,fix-orphans}.md` so Claude Code finds them.
- Logs a note about gitignoring `.sqa/findings/` if you have security concerns.

Then edit `.sqa/config.toml` to point at the files you want reviewed:

```toml
[files]
include = ["src/**/*.py"]
exclude = ["src/**/*_test.py"]
```

If your project has a quality-check command (`./runtools.sh`, `make check`, `npm test`), edit `.claude/skills/sqa-review.md` and `.claude/skills/sqa-resolve.md` to invoke it where indicated.

## Workflow

Inside a Claude Code session in the project:

| Slash command | What it does |
|---|---|
| `/sqa-review` | Run a review pass. Dispatches one `review-file` subagent per file that has changed since last review. Findings are recorded with anchors in the relevant files. |
| `/sqa-resolve auto` | Autonomously triage any new findings, then auto-fix the `auto`-class ones. |
| `/sqa-resolve interactive` | Triage new findings, then walk the `interactive`-class set with the user, fixing each in a multi-turn conversation. |
| `/sqa-status` | Report counts and breakdowns of findings. |

For very large repos or quota-paced execution, wrap with `/loop`:

```
/loop /sqa-review
/loop 1h /sqa-resolve auto
```

## CLI reference

The `sqa-tool` CLI is the deterministic backend the skills call. You can also use it directly.

```
sqa-tool init                                 # Scaffold .sqa/ and .claude/
sqa-tool needs-review [--count] [--limit N]   # List/count files needing review
sqa-tool mark-reviewed <path>                 # Record current blob hash
sqa-tool findings-for-file <path>             # Findings in scope for a file
sqa-tool list-findings [--triage=...] [--status=...] [--count] [--limit N]
sqa-tool show-finding <id>
sqa-tool status                               # Counts and breakdowns
sqa-tool record-finding --message=... --severity=... [--anchor=<file>] [--related=<file>...] [--rationale=...]
sqa-tool triage <id> auto|interactive|ignore --rationale=...
sqa-tool resolve <id> --rationale=...
sqa-tool orphans                              # Detect/fix anchor-finding inconsistencies
sqa-tool gc [--older-than=<duration>]         # Prune resolved findings (e.g. 30d)
sqa-tool diff-since-review <path>             # Diff vs last-reviewed blob
```

Run `sqa-tool <command> --help` for full options.

## Anchors

Findings live in source as short comment tags:

```python
# sqa: K7M3X
def authenticate(user, pwd):
    ...
```

Multiple findings can share a line: `# sqa: K7M3X, A4B9P`.

For module- and project-level findings (cross-cutting concerns), anchors live in `.sqa.md` files at the relevant directory:

```markdown
<!-- sqa: K7M3X -->
<!-- sqa: A4B9P -->
```

The `.sqa.md` file at any directory level scopes its findings to that directory and its descendants.

## Anchor IDs

5-character base32 strings (e.g. `K7M3X`). ~33M possible IDs; collision probability for any realistic project is negligible. Random allocation; the tool retries on the rare file-exists collision.

## Storage

```
.sqa/
  config.toml         # include/exclude globs
  file_status.json    # last-reviewed blob hash per file (fcntl-locked)
  findings/<id>.json  # one file per finding
```

Findings are tracked by git by default — the version-controlled audit trail is the primary value. For security-sensitive projects, add `.sqa/findings/` to your `.gitignore`.

## Development

```bash
git clone https://github.com/christian-trott-yourekatech/Reviewer2
cd Reviewer2
uv sync --group dev
./runtools.sh              # format, lint, type-check, test
```

## License

MIT — see [LICENSE](./LICENSE).
