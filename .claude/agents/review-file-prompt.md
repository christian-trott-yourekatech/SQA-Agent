# Code review guidance

What to look for when reviewing this project's source files. Sections
below cover the concerns reviewers should weigh against each file.
This guidance is deliberately tool-agnostic — you could hand it to any
software developer or reviewer.

Reviewers are expected to consider all sections, but only flag genuine
concerns. False positives are worse than false negatives — it's fine
to look at a section and say "nothing to flag here."

Edit this file to tailor the review to this project's needs.

## DRY / SSOT / magic numbers

Are there repeated code fragments that could be factored out? Is there
functionality duplicative with elsewhere in the project (use Grep to check)?
Is state stored locally that should be re-acquired from a single source of
truth?

**Do not flag:**
- Short blocks (~5 lines) where indirection would cost more than the duplication.
- Blocks that look syntactically similar but serve different semantic purposes.
- Cases where the "shared" helper would need multiple flags/modes per call site.

Magic numbers should usually be named. 0 and 1 are often (not always) reasonable exceptions.

## Interfaces and cohesion

- Does each function do what its name suggests, with appropriate argument names?
- Are interfaces minimal? Implementation details hidden?
- Is the file too large or low-cohesion? Would splitting help?
- Are custom types/dataclasses lean — only the fields actually needed?
- Are optionals used effectively (not as silent failure paths)?

**Do not flag** high parameter counts when each parameter is well-named, independently optional, and the function genuinely needs that surface.

## Logic and consistency

- Is the logic correct? Are edge cases handled?
- Inconsistencies in naming, argument types, or error-handling strategies?
- Any obvious optimization wins (speed or memory)?

## Comments and docs

- Are comments accurate, current, and add information beyond what the code already says?
- Stale "TODO"s for already-completed work?
- Multi-paragraph docstrings that should be one line?

## Error handling

- Are default values returned only when sensible, not as silent failure?
- Are null/None values used appropriately?
- Do real errors propagate?

## KISS / YAGNI

- Overly complex constructs?
- "Just in case" args/functions that aren't used?
- Stale/unused functions or code paths?

## Security (when relevant)

- Secrets or PII committed?
- Inputs validated? Queries injection-safe?
- Authentication/authorization correctly enforced?
- Data exposure in client bundles, logs, or error messages?

## Project-specific concerns

Add sections below for concerns specific to this project — coding
conventions, framework idioms, domain rules, anything a reviewer should
weigh that the general guidance above doesn't cover.

*(none yet)*
