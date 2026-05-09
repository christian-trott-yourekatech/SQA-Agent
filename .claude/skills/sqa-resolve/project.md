# Project configuration for sqa-resolve

This file holds project-specific bits the framework `SKILL.md` reads at
runtime. Edit the values below to match this project; the framework is
overwritten by `sqa-tool init` so any customizations belong here.

## Quality-check command

Run this command:

- Once at **Phase 0** as the pre-resolve baseline check.
- After **every fix** during auto-resolve and interactive-resolve, to catch
  regressions before moving to the next finding.

```
./runtools.sh
```

Same conventions as `sqa-review/project.md` — replace as appropriate for
this project; chain multiple commands by listing them in sequence.

## Project conventions

Optional: project-specific guidance that should bias the resolve's behavior.

- *(none yet)*
