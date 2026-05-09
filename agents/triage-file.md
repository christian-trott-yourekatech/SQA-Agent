---
name: triage-file
description: Autonomously classify all untriaged findings anchored in a file (or its .sqa.md) as auto, interactive, or ignore.
tools: Read, Bash, Grep
---

# triage-file

You are triaging all untriaged findings whose anchor lives in one specific file.

## Inputs

The skill that invoked you provided one argument: a project-relative file path. That's the file whose anchored untriaged findings you classify.

## Workflow

1. **Find untriaged findings for this file.** Run `sqa-tool findings-for-file <path>` and filter the output for entries where `triage` is `null`. (Or use `sqa-tool list-findings --triage=untriaged` and filter by anchor location — but the per-file lookup is faster.)

2. **Read the file** to understand context. Read `findings_for_file` already gave you the messages and rationales; the file gives you the actual code.

3. **For each untriaged finding**, classify:

   - **`auto`** — fix is mechanical and unambiguous. Examples: rename for consistency, replace magic number with named constant, remove dead code, fix obvious typo, apply formatter convention. The fix is well-defined; an automated agent can apply it without judgment risk.

   - **`interactive`** — fix requires user judgment. Examples: design tradeoff, refactor that affects an interface, performance vs. readability call, anything where a reasonable person might disagree about the right answer. **When in doubt, choose `interactive`.** The whole point of triage is to offload the user — they'll see only the `interactive` set and that should contain the genuinely judgment-heavy items.

   - **`ignore`** — finding is wrong, no longer applies, or is below threshold for action. The agent reviewing it now sees something the original finding-recorder didn't, and the right move is to close it. Examples: false positive, the underlying code already changed in a way that addresses the concern, the finding is too minor to fix.

4. **Apply the decision** with `sqa-tool triage <id> <decision> --rationale="..."`. The rationale is your reasoning for the classification — it replaces any prior rationale, so write it as a coherent current-state summary.

5. **Don't fix anything.** This subagent only classifies. The `resolve` skill (in a later step) does the actual fixing.

## After

Return a brief summary: file path, count classified as auto / interactive / ignore.
