# TODO

Future ideas to consider, not yet decided.

## Anchor placement: own line vs trailing comment

Currently `review-file` is free to place `# sqa: <id>` anchors either on their own line or as trailing comments on existing code lines. Trailing placement can push a line past project length limits, triggering linter complaints in the same review pass that just inserted the anchor.

Consider instructing agents to place anchors on their own line by default — preserves flow, avoids line-length violations, and makes anchors easier to scan visually. The trade-off: the anchor is one line further from the code it points at, which slightly reduces the "this anchor is about *this* line" signal.

If we go this way, the change lives in `agents/review-file.md` and possibly `agents/fix-orphans.md` (when re-inserting anchors).

## Auto-resolve: single agent vs per-finding

Today `sqa-resolve` dispatches a `resolve-file` subagent per file with auto-triaged findings, serialized one at a time (the serialization is deliberate — see prior decision on concurrent-write safety). Each subagent starts fresh and re-reads the file.

Two places this is suboptimal:
- **Repeated context-building.** A subagent fixing 5 findings in `foo.py` reads the same file, picks up the same conventions, and applies the same project style 5 times. A single agent handling all auto-resolves could amortize that.
- **Cross-finding awareness.** Two findings in the same module sometimes have related fixes (e.g. an extracted utility used by both). Per-file isolation makes that hard to spot.

Counter-considerations:
- Single-agent runs would have to carefully scope context to avoid blowing token budgets across large auto-resolve queues.
- Per-file isolation is easier to reason about for reviewer-of-the-reviewer scenarios.

Worth experimenting with after we have more dogfooding data on auto-resolve quality.
