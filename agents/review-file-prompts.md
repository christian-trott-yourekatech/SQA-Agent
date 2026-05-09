# Review prompt sections for review-file subagent

This file is read by the `review-file` subagent during a review pass. It
contains the per-section prompts the agent walks through for each file
under review. Edit these to tailor the review to this project's needs.

This file is **preserved by `sqa-tool init`** — your customizations
won't be overwritten by upgrades. The framework `review-file.md` is
overwritten on init.

The framework subagent walks each section below in order, looking for
findings. False positives are worse than false negatives — be willing to
say "no findings in this section."

## 1. DRY / SSOT / magic numbers

Are there repeated code fragments that could be factored out? Is there
functionality duplicative with elsewhere in the project (use Grep to check)?
Is state stored locally that should be re-acquired from a single source of
truth?

**Do not flag:**
- Short blocks (~5 lines) where indirection would cost more than the duplication.
- Blocks that look syntactically similar but serve different semantic purposes.
- Cases where the "shared" helper would need multiple flags/modes per call site.

Magic numbers should usually be named. 0 and 1 are often (not always) reasonable exceptions.

## 2. Interfaces and cohesion

- Does each function do what its name suggests, with appropriate argument names?
- Are interfaces minimal? Implementation details hidden?
- Is the file too large or low-cohesion? Would splitting help?
- Are custom types/dataclasses lean — only the fields actually needed?
- Are optionals used effectively (not as silent failure paths)?

**Do not flag** high parameter counts when each parameter is well-named, independently optional, and the function genuinely needs that surface.

## 3. Logic and consistency

- Is the logic correct? Are edge cases handled?
- Inconsistencies in naming, argument types, or error-handling strategies?
- Any obvious optimization wins (speed or memory)?

## 4. Comments and docs

- Are comments accurate, current, and add information beyond what the code already says?
- Stale "TODO"s for already-completed work?
- Multi-paragraph docstrings that should be one line?

## 5. Error handling

- Are default values returned only when sensible, not as silent failure?
- Are null/None values used appropriately?
- Do real errors propagate?

## 6. KISS / YAGNI

- Overly complex constructs?
- "Just in case" args/functions that aren't used?
- Stale/unused functions or code paths?

## 7. Security (when relevant)

- Secrets or PII committed?
- Inputs validated? Queries injection-safe?
- Authentication/authorization correctly enforced?
- Data exposure in client bundles, logs, or error messages?

## Project-specific sections

Add custom review sections below for concerns specific to this project.
The framework subagent treats every numbered/headed section the same way.

*(none yet)*
