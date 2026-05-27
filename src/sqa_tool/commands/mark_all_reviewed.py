"""sqa-tool mark-all-reviewed — record current blob hashes for every
file in the configured candidate set.

Bulk counterpart to ``mark-reviewed``: takes no path argument, computes
the include/exclude candidate set the same way ``needs-review`` does,
and upserts a ``file_status.json`` entry for each.  Intended for
resetting a project to a clean "everything reviewed" baseline — e.g.
after a manual pre-tool review pass, or after a sweeping refactor the
operator has confirmed is benign.

Upsert (not replace) semantics: entries for files no longer in the
candidate set (removed from ``config.include``, deleted from git) are
left in place.  They're invisible to ``needs-review`` because that
command intersects file_status against the current candidate set, so
the dead entries don't cause spurious work.  A future ``--prune`` flag
could collapse them if a project ever accumulates enough to matter.
"""

import argparse
from pathlib import Path

from sqa_tool import file_status, git_ops
from sqa_tool.commands import needs_review


def run(project_root: Path, args: argparse.Namespace) -> int:
    # Reuse needs_review's candidate-set logic so the include/exclude
    # rules and the configured-warning behavior stay in one place.
    # _candidate_files() prints its own stderr warning when include is
    # empty or the globs match no tracked files; we don't re-warn here.
    candidates = needs_review._candidate_files(project_root)
    if not candidates:
        # The warning has already been printed to stderr by
        # _candidate_files; stdout stays clean so a caller capturing
        # via $(...) sees nothing rather than a misleading "Marked 0".
        return 0

    hashes = git_ops.hash_object(project_root, candidates)
    # hash_object silently drops paths that vanish between the
    # candidate-set computation and the git call (TOCTOU race against
    # working-tree edits).  Loop over what we actually got back rather
    # than the original candidate list, so a vanished file is just
    # skipped rather than crashing on a missing-key lookup.
    for rel in candidates:
        if rel in hashes:
            file_status.update(project_root, rel, hashes[rel])

    print(f"Marked {len(hashes)} file(s) as reviewed.")
    return 0
