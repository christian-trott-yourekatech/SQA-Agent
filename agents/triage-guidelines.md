# Triage guidelines

Criteria for classifying findings as `auto`, `interactive`, or `ignore`.
Used by both `triage-file` (per-file dispatch) and `triage-general`
(`file == null` findings) — the same rules apply.

This file is preserved across `sqa-tool init` upgrades — your edits are
safe. The framework subagents (`triage-file.md`, `triage-general.md`) are
overwritten on init.

---

## Core principles

### Difficulty is not a reason to ignore

If a finding identifies a real issue but the fix is complex, requires
significant refactoring, or has multiple plausible approaches, mark it
**interactive** — not ignore. The interactive bucket exists precisely for
findings worth doing but needing discussion about approach and scope.

### Clean Code Bias

**Default to fixing, not ignoring.** A small change that makes the code
cleaner should be `auto`, not `ignore` — *unless there is a specific
reason not to do it*. The bar for ignore is **not** "this is minor" but
rather "there is a good reason to leave this as-is."

Examples of good reasons to ignore:
- The code is intentionally designed that way (and the design intent is
  either already commented or about to be — see "defensive comments"
  below).
- The fix would break something or trade off against a more important
  property.
- The finding is genuinely wrong (false positive, misreading,
  doesn't apply).

**"It's small," "not worth the effort," and "I'll do it later"** are not
good reasons to ignore. Small fixes are cheap and they compound into a
cleaner codebase over time. If you find yourself reaching for ignore on
those grounds, it should be auto instead.

### Defensive comments: the preferred way to record design intent

When a finding turns out *not* to need a behavior change but you do want
to capture "we considered this and here's why we're leaving it":

- **Prefer `auto`** with the fix being "add a clarifying comment near
  the relevant code." Write the comment-insertion instruction into the
  finding's rationale; the resolver does the actual edit. The comment
  becomes part of the source and is read naturally by every future
  reviewer (and every future maintainer).
- **`ignore` is for findings that should produce no code change at
  all** — genuinely wrong analyses, false positives in context,
  duplicates already covered by another finding. Use it when there's no
  story worth telling in source.

Why prefer the comment? Source is the durable home for "why the code is
the way it is." Future review passes start from the current source — a
well-placed comment naturally guides the next reviewer, with no
metadata to keep in sync.

**Why this is safe to do at resolve time, not triage time.** Triage
subagents run in parallel and don't edit source files (so two triagers
on different files can't collide on writes). The resolve phase is
serial — one file at a time — so it's safe to insert comments there.
That's why the comment instruction lives in the rationale: triage
plans, resolve executes.

### Comment style

When instructing the resolver to add a defensive comment, your rationale
should describe what the comment needs to say. Style guidance the
resolver will follow:

- **Length is whatever the rationale needs.** A sentence is fine; a
  short paragraph is fine if the rationale genuinely needs that much.
  Don't pad to look thorough; don't truncate to look terse.
- **Comments resolve confusion; they don't narrate development
  history.** Bad: *"We previously raised Exception here, but this was
  changed to AuthError because…"*. Good: *"Use AuthError so callers
  can branch on auth-specific failure modes."* The reader cares what
  the code does now and why, not what it used to be.
- **Don't restate the code.** If the line says `for x in items:`, the
  comment shouldn't say "iterate over items." Add information the code
  doesn't already carry — the *why* or the *constraint*.
- **Place the comment near the code it explains**, not at the top of
  the file unless the explanation is genuinely file-scope.
- **Deduplicate against existing comments.** If a nearby comment
  already covers the rationale, don't add a second one.

### Cross-cutting findings always have a home

Project-wide concerns (those with `file == null`) — missing
documentation, repo-level conventions, cross-cutting policies —
**always** have a place to land their rationale. The triager and
resolver should find it:

- Most policies have a canonical touchpoint — the public API entry,
  the main caller, the central registry. A comment there is right.
- For module-wide decisions, a module-level docstring or the module's
  `README.md` is fine.
- For genuinely distributed cases, a project-level doc
  (`ARCHITECTURE.md`, `docs/conventions.md`) is appropriate. Creating
  a small new markdown document is the right answer in the rare case
  where nothing existing fits.

"The next reviewer will just re-discover this" is **not** a valid
resolution. Every decision worth keeping is worth giving a durable
home. A few extra paragraphs of project docs over a year is cheap; the
alternative is the same finding re-surfacing on every review.

### Do the investigation, don't defer it

Investigation is the triager's job, not the user's. When a finding seems
like it could be `auto` but you're not sure of the right fix:

- Read the surrounding code, callers, and sibling patterns.
- Check whether the codebase already solves this problem elsewhere —
  utilities, established conventions, analogous functions, idioms used
  in nearby files.
- If the right answer becomes clear after investigation, mark `auto`
  with a rationale that captures your insight.

**The codebase is the first place to look for the answer, not the
user.** If the same problem is already solved elsewhere — by a utility,
a pattern, a convention — following that precedent is not a decision;
it's consistency. A menu of options is not a decision when the codebase
has already chosen.

## Pre-interactive checklist

Before marking any finding `interactive`, you must be able to answer
"yes" to all five. If you can't, go back and do the work — the finding
is likely `auto`.

1. **Did I read the surrounding code?** Not just the finding — the
   actual file, the callers, the sibling patterns within the same
   module.
2. **Did I verify any math, logic, or claims in the finding?** If the
   finding includes a formula, a type assertion, or a behavioral claim
   — check it.
3. **Did I check whether the codebase already solves this problem
   elsewhere?** Utilities, established patterns, sibling components,
   conventions.
4. **Is the "decision" I'm deferring actually a decision, or just
   following an existing convention?** If options are listed but the
   codebase already uses one of them consistently — it's pattern
   matching, not a decision.
5. **After all that, do I still genuinely need the project owner's
   input?** If the answer is no — if the right fix became clear
   through 1–4 — it's `auto`, not `interactive`.

## Auto criteria

Mark `auto` when ALL of these are true:

1. The issue is real (not a false positive or a style opinion
   masquerading as a defect).
2. The fix is obvious — there's essentially one right way.
3. The fix is low-risk — unlikely to introduce regressions.
4. The fix doesn't require design decisions or product input.

Common `auto` patterns:

- Dead code removal (unused exports, unreachable branches, stale
  imports).
- Stale or inaccurate comments and docstrings.
- Missing error handling where the codebase has an established pattern
  to follow.
- DRY violations with a clear extraction target.
- Type safety improvements where the canonical type is clear.
- Using an existing utility instead of duplicating inline logic.
- SSOT violations with a clear single owner of the truth.
- Removing redundant or no-op code.
- **Defensive-comment insertion** — when the code is intentionally as-is
  and the rationale should be captured in source.

The rationale on an `auto` finding should be specific enough for the
resolver to act without further investigation: **what to change, where,
and why.**

## Interactive criteria

Mark `interactive` when, **after investigation**, any of these still
apply:

1. **Genuinely multiple valid approaches** that depend on product or
   architecture preferences the triager can't determine alone.
2. **Significant scope with real risk** — touching core logic across
   many files where a wrong call could cause regressions.
3. **Architecture implications requiring product input** — changes to
   user-facing behavior, data contracts, or external interfaces.
4. **UX impact** — user-visible behavior change.
5. **Risk/reward tradeoff** — valuable but with meaningful regression
   risk worth discussing.
6. **Privacy/security policy** — PII handling, data exfiltration
   boundaries, or security policy where the right answer isn't obvious.
7. **New dependency** — adding a third-party package always needs the
   user's blessing.

Patterns that *seem* interactive but are usually `auto` after
investigation:

- "Touches an interface" — check how many callers exist; if one or two
  and they're all in scope, it's `auto`.
- "Utility already exists" — check if it's already imported; if so,
  using it is `auto`.
- "Type mismatch" — check what values callers actually pass; the fix
  is usually obvious.
- "Missing error handling" — if a pattern is established elsewhere,
  follow it (`auto`).
- "Multiple approaches" — if reading the code reveals one clearly
  right answer, it's `auto`.
- "Significant scope" — when the change is actually a few lines
  across a couple files, it's `auto`.
- "Component/function extraction" — when the boundary is
  self-evident, it's `auto`.
- "Type structure refactor" — if call sites already branch on the
  discriminator and pass the right fields per branch, the new type
  shape is fully determined; it's `auto`.
- "Complex domain, simple fix" — concurrency, caching, security,
  performance findings can sound high-risk, but if the fix mirrors an
  established pattern in the same module, it's `auto`. Domain
  complexity ≠ fix complexity.

## Ignore criteria

Mark `ignore` only when there is a **specific reason no code change is
warranted**. The ignore bucket is for findings where action would be
wrong, counterproductive, or genuinely inapplicable — not for findings
that seem small or low-priority, and not as a substitute for "auto with
a defensive comment."

Valid reasons to ignore:

- **Genuinely wrong finding** — the reviewer's analysis is factually
  incorrect about what the code does.
- **False positive in context** — e.g., a security flag for code that's
  intentionally client-visible by design.
- **Defensive guards misidentified as dead code** — null checks, type
  narrowing, fallback branches that protect against unexpected runtime
  conditions are safety nets, not dead code.
- **Already-documented limitations** — when the code has a comment
  explaining a known accepted tradeoff (e.g., a documented TOCTOU gap
  with a noted mitigation), the reviewer's job is to find undocumented
  issues, not re-flag acknowledged ones.
- **Duplicates covered elsewhere** — same underlying issue caught in
  multiple findings; triage the primary instance, ignore the duplicates.
- **Informational with no actionable issue** — the reviewer noted that
  something exists or is correct without identifying an actual problem.

Categories that look ignorable but are usually `auto`:

- **Magic numbers** — `auto` when the same semantic value appears 2+
  times (extract a shared constant) or when a named constant would
  clarify the value's purpose. `ignore` only when it's a one-off,
  conventional value where naming would add no clarity.
- **Minor code improvements** — `auto` if the fix is small, zero-risk,
  and leaves the code cleaner. `ignore` only if the current code is
  intentionally that way and the alternative would be worse.
- **Style/naming opinions** — `auto` when the proposed name is
  objectively clearer or completes a partial naming convention.
  `ignore` only when the proposed name isn't actually better, just
  different.
- **Premature optimization** — `auto` if the fix is trivially cheap
  (extracting a constant, hoisting an invariant). `ignore` only when
  the perf concern is irrelevant at current and foreseeable scale.

### Judgment calls

- **"Too minor / not worth the churn"** — apply Clean Code Bias. If the
  fix is zero-risk and makes the code better, it's `auto`. Ignore only
  when the change is purely cosmetic with no clarity benefit, or the
  reviewer's alternative is not actually better.
- **Intentional design choices** — capture the intent durably. If a
  defensive comment helps a future reviewer, triage `auto` with the
  comment instruction in the rationale. Mark `interactive` only when
  the choice is genuinely questionable and worth discussing.
- **Stale documentation/comments** — `auto` when the correction is
  obvious; `interactive` when the doc actively contradicts the code in
  a way that could mislead a future maintainer.

## Tiebreakers

- When in doubt between **auto** and **interactive** → choose
  `interactive`.
- When in doubt between **ignore** and **interactive** → choose
  `interactive`.
- When in doubt between **ignore** and **auto** → choose `auto`. (Clean
  Code Bias.)

## Project-specific guidance

Edit this section to capture conventions, philosophies, or constraints
specific to this project that should bias triage decisions. Examples:
*"We don't use library X — findings suggesting it should be ignored."*
*"Migration code intentionally has v1/v2 inconsistencies — those are
ignored unless they cross the v1/v2 boundary."* *"All new dependencies
require explicit approval — those findings are interactive."*

*(none yet)*
