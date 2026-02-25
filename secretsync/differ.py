"""Compute diffs between local .env state and remote backend state."""

from __future__ import annotations

from .models import DiffEntry, DiffStatus, SyncDirection, SyncPlan


# Keys that should always be masked in output (case-insensitive substring match)
_SENSITIVE_FRAGMENTS = (
    "pass",
    "password",
    "passwd",
    "secret",
    "token",
    "key",
    "api_key",
    "apikey",
    "auth",
    "credential",
    "private",
    "cert",
)


def is_sensitive(key: str) -> bool:
    """Heuristically decide whether *key* looks like a sensitive variable."""
    lower = key.lower()
    return any(frag in lower for frag in _SENSITIVE_FRAGMENTS)


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
    env_file: str = ".env",
    backend_type: str = "secrets_manager",
    dry_run: bool = False,
    prune: bool = False,
) -> SyncPlan:
    """Build a :class:`SyncPlan` for the given sync direction."""
    entries = compute_diff(local, remote)
    return SyncPlan(
        direction=direction,
        entries=entries,
        env_file=env_file,
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


def apply_plan_to_remote(plan: SyncPlan) -> dict[str, str]:
    """Compute the target remote state after applying a PUSH plan.

    Returns the new key→value dict to write to the backend.
    """
    assert plan.direction == SyncDirection.PUSH
    result: dict[str, str] = {}

    for entry in plan.entries:
        if entry.status == DiffStatus.ADDED:
            # key is only in local → push it
            result[entry.key] = entry.local_value or ""
        elif entry.status == DiffStatus.REMOVED:
            # key is only in remote
            if not plan.prune:
                result[entry.key] = entry.remote_value or ""
            # else: prune → drop it (caller deletes via backend.write_all)
        elif entry.status == DiffStatus.CHANGED:
            # local wins on push
            result[entry.key] = entry.local_value or ""
        else:
            # UNCHANGED — keep remote value
            result[entry.key] = entry.remote_value or ""

    # Remove pruned keys from result
    if plan.prune:
        for entry in plan.entries:
            if entry.status == DiffStatus.REMOVED:
                result.pop(entry.key, None)

    return result
