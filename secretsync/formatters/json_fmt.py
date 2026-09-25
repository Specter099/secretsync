"""JSON formatter for machine-readable diff output."""

from __future__ import annotations

import json

from ..differ import mask_value
from ..models import DiffStatus, SyncPlan


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
                "local": mask_value(entry.key, entry.local_value, mask),
                "remote": mask_value(entry.key, entry.remote_value, mask),
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
