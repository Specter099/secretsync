"""Core data models for secretsync."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DiffStatus(str, Enum):
    """Describes how a key differs between local and remote."""

    ADDED = "added"        # exists locally, not in remote
    REMOVED = "removed"    # exists in remote, not locally
    CHANGED = "changed"    # exists in both, values differ
    UNCHANGED = "unchanged"  # exists in both, values identical


class SyncDirection(str, Enum):
    PUSH = "push"   # local → remote
    PULL = "pull"   # remote → local


@dataclass
class EnvVar:
    """A single key/value pair from a .env file or remote backend."""

    key: str
    value: str

    def masked_value(self, mask_char: str = "*", visible_chars: int = 0) -> str:
        """Return value with all but the first *visible_chars* characters masked."""
        if not self.value:
            return self.value
        if visible_chars <= 0:
            return mask_char * min(len(self.value), 8)
        prefix = self.value[:visible_chars]
        return prefix + mask_char * max(0, len(self.value) - visible_chars)


@dataclass
class DiffEntry:
    """A single row in a computed diff between local and remote env vars."""

    key: str
    status: DiffStatus
    local_value: Optional[str] = None
    remote_value: Optional[str] = None

    @property
    def is_change(self) -> bool:
        return self.status != DiffStatus.UNCHANGED

    def display_values(
        self, mask_sensitive: bool = True
    ) -> tuple[str, str]:
        """Return (local_display, remote_display) with optional masking."""
        local = self.local_value or ""
        remote = self.remote_value or ""

        if mask_sensitive:
            mask = lambda v: ("*" * min(len(v), 8)) if v else ""  # noqa: E731
            local = mask(local)
            remote = mask(remote)

        return local, remote


@dataclass
class SyncPlan:
    """The complete plan for a push or pull operation."""

    direction: SyncDirection
    entries: list[DiffEntry] = field(default_factory=list)
    env_file: str = ".env"
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
