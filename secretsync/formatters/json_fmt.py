"""JSON formatter for machine-readable diff output."""

from __future__ import annotations

import json

from ..differ import is_sensitive
from ..models import DiffStatus, SyncPlan


def _mask(value: str | None, key: str, mask_sensitive: bool) -> str | None:
    if value is None:
        return None
    if mask_sensitive and is_sensitive(key):
        return "*" * min(len(value), 8)
    return value


def format_json(plan: SyncPlan, *, mask: bool = True) -> str:
    """Render the plan as a JSON string.

    Schema::

        {
          "direction": "push",
          "backend": "secrets_manager",
          "dry_run": false,
          "summary": {"added": 1, "removed": 0, "changed": 2, "unchanged": 5},
          "entries": [
            {
              "key": "DB_HOST",
              "status": "unchanged",
              "local": "localhost",
              "remote": "localhost"
            },
            ...
          ]
        }
    """
    entries_out = []
    for entry in plan.entries:
        entries_out.append(
            {
                "key": entry.key,
                "status": entry.status.value,
                "local": _mask(entry.local_value, entry.key, mask),
                "remote": _mask(entry.remote_value, entry.key, mask),
            }
        )

    summary = {
        "added": sum(1 for e in plan.entries if e.status == DiffStatus.ADDED),
        "removed": sum(1 for e in plan.entries if e.status == DiffStatus.REMOVED),
        "changed": sum(1 for e in plan.entries if e.status == DiffStatus.CHANGED),
        "unchanged": sum(1 for e in plan.entries if e.status == DiffStatus.UNCHANGED),
    }

    output = {
        "direction": plan.direction.value,
        "backend": plan.backend_type,
        "dry_run": plan.dry_run,
        "summary": summary,
        "entries": entries_out,
    }

    return json.dumps(output, indent=2, ensure_ascii=False)
