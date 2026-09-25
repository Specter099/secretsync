"""Compute diffs between local .env state and remote backend state."""

from __future__ import annotations

from .models import DiffEntry, DiffStatus, SyncDirection, SyncPlan


def mask_value(value: str | None, mask: bool) -> str | None:
    """Return *value* replaced by up to 8 ``*`` when *mask* is on."""
    if value is not None and mask:
        return "*" * min(len(value), 8)
    return value


def compute_diff(
    local: dict[str, str],
    remote: dict[str, str],
) -> list[DiffEntry]:
    """Compute a full diff between *local* and *remote* env var mappings.

    Returns a list of :class:`DiffEntry` objects sorted by key, covering:
    - ADDED:     present in local, absent in remote
    - REMOVED:   present in remote, absent in local
    - CHANGED:   present in both, different values
    - UNCHANGED: present in both, identical values
    """
    all_keys = sorted(set(local) | set(remote))
    entries: list[DiffEntry] = []

    for key in all_keys:
        in_local = key in local
        in_remote = key in remote

        if in_local and not in_remote:
            entries.append(
                DiffEntry(
                    key=key,
                    status=DiffStatus.ADDED,
                    local_value=local[key],
                    remote_value=None,
                )
            )
        elif in_remote and not in_local:
            entries.append(
                DiffEntry(
                    key=key,
                    status=DiffStatus.REMOVED,
                    local_value=None,
                    remote_value=remote[key],
                )
            )
        elif local[key] != remote[key]:
            entries.append(
                DiffEntry(
                    key=key,
                    status=DiffStatus.CHANGED,
                    local_value=local[key],
                    remote_value=remote[key],
                )
            )
        else:
            entries.append(
                DiffEntry(
                    key=key,
                    status=DiffStatus.UNCHANGED,
                    local_value=local[key],
                    remote_value=remote[key],
                )
            )

    return entries


def build_sync_plan(
    local: dict[str, str],
    remote: dict[str, str],
    direction: SyncDirection,
    *,
    backend_type: str = "secrets_manager",
    dry_run: bool = False,
    prune: bool = False,
) -> SyncPlan:
    """Build a :class:`SyncPlan` for the given sync direction."""
    entries = compute_diff(local, remote)
    return SyncPlan(
        direction=direction,
        entries=entries,
        backend_type=backend_type,
        dry_run=dry_run,
        prune=prune,
    )


def apply_plan_to_local(plan: SyncPlan) -> dict[str, str]:
    """Compute the target local state after applying a PULL plan.

    Returns the new key→value dict to write to the .env file.
    """
    assert plan.direction == SyncDirection.PULL
    result: dict[str, str] = {}

    for entry in plan.entries:
        if entry.status == DiffStatus.REMOVED:
            # key is only in remote → add to local
            result[entry.key] = entry.remote_value or ""
        elif entry.status == DiffStatus.ADDED:
            # key is only in local
            if not plan.prune:
                result[entry.key] = entry.local_value or ""
            # else: prune → drop it
        elif entry.status == DiffStatus.CHANGED:
            # remote wins on pull
            result[entry.key] = entry.remote_value or ""
        else:
            # UNCHANGED — keep local value
            result[entry.key] = entry.local_value or ""

    return result


def remote_changes(plan: SyncPlan) -> tuple[dict[str, str], list[str]]:
    """Return the ``(updates, deletes)`` a PUSH plan needs on the remote.

    Only added/changed keys are written; unchanged keys are never rewritten.
    Remote-only keys are deleted only when the plan prunes.
    """
    assert plan.direction == SyncDirection.PUSH
    updates = {
        e.key: e.local_value or ""
        for e in plan.entries
        if e.status in (DiffStatus.ADDED, DiffStatus.CHANGED)
    }
    deletes = [e.key for e in plan.entries if e.status == DiffStatus.REMOVED] if plan.prune else []
    return updates, deletes
