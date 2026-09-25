"""Core data models for secretsync."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DiffStatus(StrEnum):
    """Describes how a key differs between local and remote."""

    ADDED = "added"  # exists locally, not in remote
    REMOVED = "removed"  # exists in remote, not locally
    CHANGED = "changed"  # exists in both, values differ
    UNCHANGED = "unchanged"  # exists in both, values identical


class SyncDirection(StrEnum):
    PUSH = "push"  # local → remote
    PULL = "pull"  # remote → local


@dataclass
class DiffEntry:
    """A single row in a computed diff between local and remote env vars."""

    key: str
    status: DiffStatus
    local_value: str | None = None
    remote_value: str | None = None

    @property
    def is_change(self) -> bool:
        return self.status != DiffStatus.UNCHANGED


@dataclass
class SyncPlan:
    """The complete plan for a push or pull operation."""

    direction: SyncDirection
    entries: list[DiffEntry] = field(default_factory=list)
    backend_type: str = "secrets_manager"
    dry_run: bool = False
    prune: bool = False

    @property
    def changes(self) -> list[DiffEntry]:
        """Entries that will result in a write (excludes UNCHANGED)."""
        return [e for e in self.entries if e.is_change]

    @property
    def has_deletions(self) -> bool:
        if self.direction == SyncDirection.PUSH:
            return any(e.status == DiffStatus.REMOVED for e in self.entries)
        return any(e.status == DiffStatus.ADDED for e in self.entries)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)
