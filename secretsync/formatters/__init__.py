"""Output formatters for diff/status display."""

from __future__ import annotations

from ..models import SyncPlan
from .json_fmt import format_json
from .terminal import format_table

__all__ = ["format_table", "format_json", "render_plan"]


def render_plan(plan: SyncPlan, fmt: str = "table", mask: bool = True) -> str:
    """Render a :class:`SyncPlan` using the requested format.

    Args:
        plan: The sync plan to render.
        fmt: ``"table"`` for Rich terminal output, ``"json"`` for JSON.
        mask: When True, mask sensitive values.

    Returns:
        A string representation of the plan (may contain ANSI codes for table).
    """
    if fmt == "json":
        return format_json(plan, mask=mask)
    return format_table(plan, mask=mask)
