# Project configuration for sqa-review

This file holds project-specific bits the framework `SKILL.md` reads at
runtime. Edit the values below to match this project; the framework is
overwritten by `sqa-tool init` so any customizations belong here.

## Quality-check command

Run this command as the **Phase 0** pre-review baseline check (and as the
post-review final check, if desired). The framework reads this file to
determine what to invoke.

```
./runtools.sh
```

If this project uses a different convention (`make check`, `npm test`,
`cargo test`, etc.), replace the command above. Use multiple commands by
listing them in sequence; the framework will run them all and treat any
non-zero exit as a failure.

## Project conventions

Optional: project-specific guidance that should bias the review's behavior.
The framework prompt instructs `review-file` subagents to read this section
when reviewing files in this project.

Examples (delete the placeholder line and add your own as needed):

- *(none yet)*
