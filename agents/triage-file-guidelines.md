# Triage guidelines for triage-file subagent

This file is read by the `triage-file` subagent during the autonomous
triage phase of `sqa-resolve`. It contains the criteria for classifying
each finding as `auto`, `interactive`, or `ignore`. Edit to tailor to
this project's needs.

This file is **preserved by `sqa-tool init`** — your customizations
won't be overwritten by upgrades. The framework `triage-file.md` is
overwritten on init.

## Core principles

### Difficulty is not a reason to ignore

If a finding identifies a real issue but the fix is complex, requires significant refactoring, or has multiple approaches, mark it as **interactive** — not ignore. The interactive bucket exists precisely for findings worth doing but needing discussion about approach and scope.

### Clean Code Bias

**Default to fixing, not ignoring.** A small change that makes the code cleaner should be `auto`, not `ignore` — *unless there is a specific reason not to do it*. The bar for ignore is **not** "this is minor" but rather "there is a good reason to leave this as-is."

Examples of good reasons to ignore:
- The code is intentionally designed that way (and either commented as such or about to be).
- The fix would break something or trade off against a more important property.
- The finding is genuinely wrong (false positive, misreading, doesn't apply).

**"It's small," "it's not worth the effort," or "I'll do it later" are not good reasons** to ignore. Small fixes are cheap and they compound into a cleaner codebase over time. If you find yourself reaching for ignore on those grounds, it should be auto instead.

### Where does the rationale live: comment or persisted finding?

When a finding turns out not to need a code change but you *do* want to record "we considered this and here's why we're leaving it," there are two durable places the rationale can live:

- **Inline comment in the code** — triage `auto` with the fix being "add a clarifying comment," then `resolve` (which deletes the finding JSON). Rationale lives next to the code it explains.
- **Persisted ignore-rationale** — triage `ignore` with the explanation in the rationale field. The finding stays in `.sqa/findings/<id>.json` and surfaces in every future `findings-for-file` scope walk.

Both successfully prevent re-flagging on subsequent review passes (a reviewer reading the source sees the comment; a reviewer loading prior scope findings sees the ignore). The decision is about **where the rationale is most useful**, not which mechanism is more durable.

**Prefer an inline comment + resolve when:**
- The rationale is tied to specific lines of code — function-level mechanism, a particular except clause, a magic constant's origin, a load-bearing ordering.
- A reader looking at the code in isolation might independently question it ("why does this only catch one exception type?") and the comment answers them on the spot, with no indirection.
- The comment text is short — a sentence or two. Long rationales become intrusive in source.
- A future editor might be tempted to "clean up" the apparent oddity, and a comment is the cheapest way to flag intent.

**Prefer ignore (keep the finding) when:**
- The rationale is policy- or module-level — cross-cutting decisions that don't belong on any single line ("we don't validate X across this module because…").
- The explanation would clutter the code: long enough to be intrusive, or it'd repeat itself in multiple places.
- The audience is primarily *reviewers* (human or LLM doing future review passes), not editors of the code. The persisted finding surfaces during scope walks; that's its native habitat.
- The finding is "we considered this concern, decided to live with it" — exactly the kind of accumulated review state the persisted-findings system exists for.

**Default for minor nit-picks** — Clean Code Bias still wins. If the change is small and zero-risk, just `auto` it and move on. The dichotomy above is for findings where action is genuinely *not* the right call; don't use it to dress up "I don't feel like fixing this."

**Anti-pattern**: triaging `ignore` AND adding an inline comment. That's belt and suspenders — pick one. If the rationale is worth committing to source, resolve the finding (the comment IS the durable record). If the rationale is reviewer-state-only, the ignore-finding alone is enough.

### Do the investigation, don't defer it

Investigation is the triager's job, not the user's. When a finding seems like it could be auto but you're not sure of the right fix:

- Read the surrounding code, callers, and sibling patterns.
- Check whether the codebase already solves this problem elsewhere — utilities, established conventions, analogous functions, idioms used in nearby files.
- If the right answer becomes clear after investigation, mark it `auto` with a rationale that captures your insight.

**The codebase is the first place to look for the answer, not the user.** If the same problem is already solved elsewhere — by a utility, a pattern, a convention — then following that precedent is not a decision, it's consistency. **A menu of options is not a decision when the codebase has already chosen.**

## Pre-interactive checklist

Before marking any finding `interactive`, you must be able to answer "yes" to all five of these. If you can't, go back and do the work — the finding is likely auto.

1. **Did I read the surrounding code?** Not just the finding — the actual file, the callers, the sibling patterns within the same module.
2. **Did I verify any math, logic, or claims in the finding?** If the finding includes a formula, a type assertion, or a behavioral claim — check it.
3. **Did I check whether the codebase already solves this problem elsewhere?** Utilities, established patterns, sibling components, conventions.
4. **Is the "decision" I'm deferring actually a decision, or just following an existing convention?** If options are listed but the codebase already uses one of them consistently — it's pattern matching, not a decision.
5. **After all that, do I still genuinely need the project owner's input?** If the answer is no — if the right fix became clear through 1–4 — it's `auto`, not `interactive`.

## Auto criteria

Mark `auto` when ALL of these are true:

1. The issue is real (not a false positive or a style opinion masquerading as a defect).
2. The fix is obvious — there's essentially one right way.
3. The fix is low-risk — unlikely to introduce regressions.
4. The fix doesn't require design decisions or product input.

Common auto patterns:

- Dead code removal (unused exports, unreachable branches, stale imports).
- Stale or inaccurate comments and docstrings.
- Missing error handling where the codebase has an established pattern to follow.
- DRY violations with a clear extraction target.
- Type safety improvements where the canonical type is clear.
- Using an existing utility instead of duplicating inline logic.
- SSOT violations with a clear single owner of the truth.
- Removing redundant or no-op code.

The rationale on an auto finding should be specific enough for the resolver to act on without further investigation: **what to change, where, and why.**

## Interactive criteria

Mark `interactive` when, **after investigation**, any of these still apply:

1. **Genuinely multiple valid approaches** that depend on product or architecture preferences the triager can't determine alone.
2. **Significant scope with real risk** — touching core logic across many files where a wrong call could cause regressions.
3. **Architecture implications requiring product input** — changes to user-facing behavior, data contracts, or external interfaces.
4. **UX impact** — user-visible behavior change.
5. **Risk/reward tradeoff** — valuable but with meaningful regression risk worth discussing.
6. **Privacy/security policy** — PII handling, data exfiltration boundaries, or security policy where the right answer isn't obvious.
7. **New dependency** — adding a third-party package always needs the user's blessing.

Patterns that *seem* interactive but are usually auto after investigation:

- "Touches an interface" — check how many callers exist; if one or two and they're all in scope, it's auto.
- "Utility already exists" — check if it's already imported; if so, using it is auto.
- "Type mismatch" — check what values callers actually pass; the fix is usually obvious.
- "Missing error handling" — if a pattern is established elsewhere, follow it (auto).
- "Multiple approaches" — if reading the code reveals one clearly right answer, it's auto.
- "Significant scope" — when the change is actually a few lines across a couple files, it's auto.
- "Component/function extraction" — when the boundary is self-evident, it's auto.
- "Type structure refactor" — if call sites already branch on the discriminator and pass the right fields per branch, the new type shape is fully determined; it's auto.
- "Complex domain, simple fix" — concurrency, caching, security, performance findings can sound high-risk, but if the fix mirrors an established pattern in the same module, it's auto. The complexity of the *problem domain* is not the same as the complexity of the *fix*.

## Ignore criteria

Mark `ignore` only when there is a **specific reason not to fix**. The ignore bucket is for findings where action would be wrong, counterproductive, or genuinely inapplicable — not for findings that seem small or low-priority.

In v2, an ignored finding persists with its rationale. The reviewer sees it on every subsequent review and respects it — so the rationale field is the durable explanation. Spend it well: capture *why* the finding doesn't apply, in enough detail that a future reader (reviewer or human) can tell at a glance.

Valid reasons to ignore:

- **Genuinely wrong finding** — the reviewer's analysis is factually incorrect about what the code does.
- **False positive in context** — e.g., a security flag for code that's intentionally client-visible by design.
- **Defensive guards misidentified as dead code** — null checks, type narrowing, fallback branches that protect against unexpected runtime conditions are safety nets, not dead code.
- **Already-documented limitations** — when the code has a comment explaining a known accepted tradeoff (e.g., a documented TOCTOU gap with a noted mitigation), the reviewer's job is to find undocumented issues, not re-flag acknowledged ones.
- **Duplicates covered elsewhere** — same underlying issue caught in multiple files; triage the primary instance, ignore the duplicates.
- **Informational with no actionable issue** — the reviewer noted that something exists or is correct without identifying an actual problem.

Categories that look ignorable but are usually auto:

- **Magic numbers** — `auto` when the same semantic value appears 2+ times (extract a shared constant) or when a named constant would clarify the value's purpose. `ignore` only when it's a one-off, conventional value where naming would add no clarity.
- **Minor code improvements** — `auto` if the fix is small, zero-risk, and leaves the code cleaner. `ignore` only if the current code is intentionally that way and the alternative would be worse.
- **Style/naming opinions** — `auto` when the proposed name is objectively clearer or completes a partial naming convention. `ignore` only when the proposed name isn't actually better, just different.
- **Premature optimization** — `auto` if the fix is trivially cheap (extracting a constant, hoisting an invariant). `ignore` only when the perf concern is irrelevant at current and foreseeable scale.

### Judgment calls

- **"Too minor / not worth the churn"** — apply Clean Code Bias. If the fix is zero-risk and makes the code better, it's auto. Ignore only when the change is purely cosmetic with no clarity benefit, or the reviewer's alternative is not actually better.
- **Intentional design choices** — capture the intent durably. Whether that lives in an inline comment (triage `auto`, then resolve) or a persisted ignore-rationale depends on the audience and reach of the explanation; see "Where does the rationale live: comment or persisted finding?" above. Mark `interactive` only when the choice is genuinely questionable and worth discussing.
- **Stale documentation/comments** — `auto` when the correction is obvious; `interactive` when the doc actively contradicts the code in a way that could mislead a future maintainer.

## Tiebreakers

- When in doubt between **auto** and **interactive** → choose `interactive`.
- When in doubt between **ignore** and **interactive** → choose `interactive`.
- When in doubt between **ignore** and **auto** → choose `auto`. (Clean Code Bias.)

## Project-specific guidance

*(Edit this section to capture conventions, philosophies, or constraints specific to this project that should bias triage decisions. Examples: "We don't use library X — findings suggesting it should be ignored." "Migration code intentionally has v1/v2 inconsistencies — those are ignored unless they cross the v1/v2 boundary." "All new dependencies require explicit approval — those findings are interactive.")*

*(none yet)*
