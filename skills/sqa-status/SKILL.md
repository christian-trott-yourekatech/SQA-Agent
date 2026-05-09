---
name: sqa-status
description: Report on the current state of findings in this project — counts and breakdowns by triage, severity, and status.
---

# sqa-status

Report on the SQA review state.

1. Run `sqa-tool status`. This returns a JSON payload with `total`, `by_triage`, `by_severity`, `by_status`.
2. Present the results conversationally. Highlight:
   - Total findings.
   - How many are untriaged (need review by you/user).
   - How many are auto-class open (ready for `/sqa-resolve auto`).
   - How many are interactive-class open (ready for `/sqa-resolve interactive`).
   - How many are resolved (recently closed).
3. If the user asks about a specific scope (e.g. "how many in `auth/`?"), run `sqa-tool list-findings <path> -r --count` etc. as needed.
4. If the user asks to see specific findings, use `sqa-tool list-findings` with appropriate filters and pretty-print.

Keep the report concise. The user is asking for a quick read on state, not an exhaustive inventory.
