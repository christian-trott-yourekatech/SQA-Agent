"""sqa-tool triage / resolve — finding state transitions on the active result.

Both commands operate **only** on the most recent (active) result file.
Historical results are read-only; pointing these commands at one via
``--from`` would be a foot-gun, so we don't offer that flag here. The state
machine itself is implemented in :mod:`sqa_tool.result_file`; this module
is the thin CLI wrapper.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from sqa_tool import paths
from sqa_tool.result_file import (
    Finding,
    StateTransitionError,
    active_result_or_exit_message,
    apply_resolve,
    apply_triage,
    find_by_id,
    with_locked_result,
)


def _mutate_active_finding(
    project_root: Path,
    args: argparse.Namespace,
    mutate: Callable[[Finding], None],
) -> tuple[int, Finding] | None:
    """Shared scaffolding for the two finding-mutation commands.

    Validates ``args.id`` (must be a positive int — argparse has already
    enforced int-ness via ``type=int``, so the only check left is the
    "> 0" guard), resolves the active result path, takes the per-result
    file lock, looks up the finding, and runs ``mutate(finding)`` under
    the lock. Returns ``(finding_id, finding)`` on success so callers
    can print a confirmation message; returns ``None`` and prints an
    appropriate error to stderr on any failure (invalid id, no active
    result, unknown id, illegal state transition). Callers translate the
    ``None`` into a non-zero CLI exit.
    """
    finding_id = args.id
    if finding_id <= 0:
        print(
            f"error: invalid finding ID: {finding_id!r} (expected a positive int)",
            file=sys.stderr,
        )
        return None

    result_path = active_result_or_exit_message(paths.sqa_dir(project_root))
    if result_path is None:
        return None

    try:
        with with_locked_result(result_path) as (_, findings):
            f = find_by_id(findings, finding_id)
            mutate(f)
            # Snapshot the finding under the lock so the caller can read
            # post-mutation fields (e.g. status) without re-acquiring it.
            return finding_id, f
    except KeyError:
        print(f"error: no finding with id {finding_id}", file=sys.stderr)
        return None
    except StateTransitionError as e:
        print(f"error: {e}", file=sys.stderr)
        return None


def triage(project_root: Path, args: argparse.Namespace) -> int:
    """Set triage decision and rationale on a finding in the active result.

    Honors the state machine in :mod:`sqa_tool.result_file`: ``ignore``
    flips status to ``resolved``; un-ignoring (from ``ignore+resolved``
    back to ``auto``/``interactive``) flips status to ``open``;
    re-triaging an action-resolved finding is rejected.
    """
    result = _mutate_active_finding(
        project_root,
        args,
        lambda f: apply_triage(f, args.decision, args.rationale),
    )
    if result is None:
        return 1
    finding_id, f = result
    # `f.status` is read while the snapshot is still fresh — the
    # confirmation stays honest against the state machine even if the
    # transition rules later change (e.g. some `auto` re-triage starts
    # implying status=resolved).
    print(f"triaged {finding_id}: {args.decision} ({f.status})")
    return 0


def resolve(project_root: Path, args: argparse.Namespace) -> int:
    """Mark a finding resolved by flipping its ``status`` to ``resolved``.

    Rejects untriaged findings (need triage first) and already-resolved
    findings (idempotency would mask bugs).
    """
    result = _mutate_active_finding(
        project_root,
        args,
        lambda f: apply_resolve(f, args.rationale),
    )
    if result is None:
        return 1
    finding_id, _ = result
    print(f"resolved {finding_id}: {args.rationale}")
    return 0
