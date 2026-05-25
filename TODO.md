# TODO

Future ideas to consider, not yet decided.

## Agent dispatching: context vs focus

The framework currently fans out three different phases to subagents —
review, triage, and auto-resolve — and the fan-out granularity is "one
subagent per file" in every case. That's a defensible default but it's
worth questioning across all three phases together, since they share the
same underlying trade-off: **how to balance fresh-context isolation
against amortized context-building and cross-finding awareness.**

### Auto-resolve

Today `sqa-resolve` dispatches a `resolve-file` subagent per file,
serialized one at a time (the serialization is deliberate — see prior
decision on concurrent-write safety).

Per-file: each subagent starts fresh, re-reads the file, re-picks up
project conventions. For 5 findings in `foo.py`, that's 5 bootstraps.
Cross-finding awareness (two related fixes in the same module) is hard.

Options to consider:
- **Multiple files per agent.** Batch several files into one agent's
  context — amortizes convention-picking-up and lets it see patterns
  across the batch.
- **Single agent for the whole queue.** Maximum context reuse, but token
  budgets get tight on large auto-resolve queues. Open question: can
  subagents auto-compact mid-run, or does context exhaustion just
  terminate them? If they can compact, a single-agent approach becomes
  much more attractive.
- **Status quo with deliberate batching.** Keep per-file but feed the
  agent a small "project-conventions" summary harvested from earlier
  batches.

### Triage

`triage-file` subagents currently run one-per-file too (during the
autonomous triage phase of `sqa-resolve`). Each one loads
`triage-guidelines.md`, reads `findings-for-file`, reads the file, and
emits triage decisions.

The per-file dispatch makes parallelism cheap, but triage *quality*
benefits from project-level intuition: knowing what counts as "normal
style here," what the recurring false-positive patterns are, what the
project's bias on a given dimension is. That intuition is hard to build
inside one file's view.

A single triage agent (or batched groups) could develop that intuition
by seeing patterns across files — at the cost of serializing triage and
consuming more context per run.

### Review

Each `review-file` subagent does the full review walk against one file.

This is in contrast to the v1 reviewer, which dispatched **separate
agents per prompt aspect** — each focused on one concern at a time, on
one file.

Current approach: 1 agent × 1 file = fast and cheap, but each concern
gets diluted attention. The agent is doing both "scan for everything"
and "decide what to flag" in one breath.

v1-style focused approach: N agents × 1 file × narrow lens. Each agent
is single-minded — looks only at its slice — which produces deeper
findings per topic, but at N× the dispatch and file-read cost.

Open questions worth experimenting with:
- Is the current breadth-over-depth trade-off costing us real findings,
  or is breadth working fine in practice?
- If we did go back to per-aspect agents, can we batch *aspects* across
  multiple files (one Security agent that scans N files) to recover
  some of the amortization?
- Are some aspects (e.g. Security) high-value enough to deserve their
  own focused agent even if the others stay bundled?

### The shared underlying question

All three of these are facets of the same trade-off, and the right
answer probably isn't uniform across phases — auto-resolve cares most
about cross-finding awareness, triage cares most about
project-intuition, and review cares most about per-aspect focus. Worth
treating them as independent experiments rather than picking one
philosophy globally.

## Result-file retention / cleanup

Result files accumulate one-per-session. There's no built-in pruning;
the user is expected to gitignore them and clean up by hand. If the
disk-usage cost becomes annoying, consider:
- `sqa-tool prune --older-than=30d` to remove old result files.
- An auto-prune knob in `config.toml`.

Deferred until real usage surfaces the need.

## Persistent-findings opt-in

The current design records findings to a per-session result file and
relies on defensive comments in source for design intent that needs to
outlive a session (see `Docs/design.md` § 6.4). If that turns out
insufficient in practice — specifically, if persistent
"already-considered" findings get re-flagged every review and the cost
of re-triage hurts enough to matter — consider a `--persistent` opt-in
mode at init time. Not designed yet; would re-introduce a meaningful
chunk of bookkeeping (per-finding records, in-source anchors, orphan
reconciliation) so the bar for adding it is real pain in practice, not
hypothetical concern.
