"""Rich terminal table formatter for diff output."""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..differ import is_sensitive
from ..models import DiffStatus, SyncPlan

# Status → (symbol, Rich style)
_STATUS_STYLE: dict[DiffStatus, tuple[str, str]] = {
    DiffStatus.ADDED: ("+", "bold green"),
    DiffStatus.REMOVED: ("-", "bold red"),
    DiffStatus.CHANGED: ("~", "bold yellow"),
    DiffStatus.UNCHANGED: ("=", "dim"),
}


def _mask(value: str | None, key: str, mask_sensitive: bool) -> str:
    if value is None:
        return ""
    if mask_sensitive and is_sensitive(key):
        return "*" * min(len(value), 8)
    return value


def format_table(plan: SyncPlan, *, mask: bool = True) -> str:
    """Render the plan as a Rich table and return the string output."""
    table = Table(
        title=f"Diff — {plan.direction.value.upper()}  [{plan.backend_type}]",
        show_header=True,
        header_style="bold cyan",
        expand=False,
        box=None,
        show_edge=True,
        padding=(0, 1),
    )

    table.add_column("", width=2, no_wrap=True)          # status symbol
    table.add_column("Key", style="bold", no_wrap=True)
    table.add_column("Local", no_wrap=False)
    table.add_column("Remote", no_wrap=False)

    for entry in plan.entries:
        symbol, style = _STATUS_STYLE[entry.status]
        local_val = _mask(entry.local_value, entry.key, mask)
        remote_val = _mask(entry.remote_value, entry.key, mask)

        table.add_row(
            Text(symbol, style=style),
            Text(entry.key, style=style if entry.is_change else ""),
            Text(local_val or "—", style=style if entry.status == DiffStatus.ADDED else ""),
            Text(remote_val or "—", style=style if entry.status == DiffStatus.REMOVED else ""),
        )

    buf = StringIO()
    console = Console(file=buf, highlight=False, no_color=False)
    console.print(table)

    # Summary line
    added = sum(1 for e in plan.entries if e.status == DiffStatus.ADDED)
    removed = sum(1 for e in plan.entries if e.status == DiffStatus.REMOVED)
    changed = sum(1 for e in plan.entries if e.status == DiffStatus.CHANGED)
    unchanged = sum(1 for e in plan.entries if e.status == DiffStatus.UNCHANGED)

    summary_parts = []
    if added:
        summary_parts.append(f"[bold green]+{added} added[/]")
    if removed:
        summary_parts.append(f"[bold red]-{removed} removed[/]")
    if changed:
        summary_parts.append(f"[bold yellow]~{changed} changed[/]")
    if unchanged:
        summary_parts.append(f"[dim]={unchanged} unchanged[/]")

    if summary_parts:
        console.print("  " + "  ".join(summary_parts))

    if plan.dry_run:
        console.print("\n[bold yellow]Dry-run mode — no changes will be written.[/]")

    return buf.getvalue()
