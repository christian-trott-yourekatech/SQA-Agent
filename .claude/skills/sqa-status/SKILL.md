---
name: sqa-status
description: Report on the current state of findings in the active review session — counts and breakdowns by triage, severity, and status.
---

# sqa-status

Report on the SQA review state.

1. Run `sqa-tool status`. This returns a JSON payload with `total`,
   `by_triage`, `by_severity`, `by_status`, and `result_file` (the
   active result file path, or `null` if no session has been started).

2. If `result_file` is `null`, tell the user no review session is
   active — they should run `/sqa-review` first.

3. Otherwise present the results conversationally. Highlight:
   - Total findings in this session.
   - How many are untriaged (need triage via `/sqa-resolve`).
   - How many are `auto` open (ready for `/sqa-resolve auto`).
   - How many are `interactive` open (ready for `/sqa-resolve
     interactive`).
   - How many are resolved (closed in this session — includes both
     action-resolved and `ignore`-resolved).

4. If the user asks to inspect specific findings, use
   `sqa-tool list-findings` with the appropriate `--triage` /
   `--status` filters, or `sqa-tool show-finding <id>` for a single
   finding. Use `sqa-tool findings-for-file <path>` to scope to one
   file.

5. To inspect a previous session's results, pass `--from <result-file>`
   to any of the read commands (`status`, `list-findings`,
   `show-finding`, `findings-for-file`). Historical results are
   read-only.

Keep the report concise. The user is asking for a quick read on state,
not an exhaustive inventory.
