"""Click CLI entrypoint for secretsync."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from botocore.exceptions import BotoCoreError, ClientError
from rich.console import Console
from rich.markup import escape
from rich.prompt import Confirm

from .backends import get_backend
from .config import load_config, validate_config
from .differ import apply_plan_to_local, build_sync_plan, remote_changes
from .env_file import parse_env_file, write_env_file
from .formatters import render_plan
from .models import SyncDirection

console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Shared options
# ---------------------------------------------------------------------------

_env_file_option = click.option(
    "--env-file",
    default=".env",
    show_default=True,
    help="Path to the local .env file.",
    metavar="FILE",
)
_config_option = click.option(
    "--config",
    default=None,
    help="Path to config file. [default: .secretsync.toml if present]",
    metavar="FILE",
)
_format_option = click.option(
    "--format",
    "output_format",
    default="table",
    type=click.Choice(["table", "json"], case_sensitive=False),
    show_default=True,
    help="Output format.",
)
_dry_run_option = click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview changes without writing anything.",
)
_force_option = click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Skip confirmation prompts (suitable for CI).",
)
_prune_option = click.option(
    "--prune",
    is_flag=True,
    default=False,
    help="Delete remote keys absent locally (push) or local keys absent from remote (pull).",
)
_no_mask_option = click.option(
    "--mask/--no-mask",
    default=True,
    show_default=True,
    help="Mask all values in output (use --no-mask to show plaintext).",
)


def _abort(msg: str, exit_code: int = 1) -> None:
    console.print(f"[bold red]Error:[/] {escape(msg)}")
    sys.exit(exit_code)


def _warn_no_mask(mask: bool) -> None:
    """Print a warning when --no-mask is active."""
    if not mask:
        console.print(
            "[bold yellow]Warning:[/] --no-mask is active. "
            "Secret values will be displayed in plaintext."
        )


def _check_env_file_path(env_file: str) -> None:
    """Warn if the env file path contains traversal components."""
    parts = Path(env_file).parts
    if ".." in parts:
        resolved = Path(env_file).resolve()
        console.print(
            f"[bold yellow]Warning:[/] --env-file target '{escape(env_file)}' "
            f"contains path traversal (resolves to {escape(str(resolved))})."
        )


def _load_and_validate(config_path: str):
    cfg = load_config(config_path)
    errors = validate_config(cfg)
    if errors:
        for err in errors:
            console.print(f"[bold red]Config error:[/] {escape(err)}")
        sys.exit(1)
    return cfg


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


class _CliGroup(click.Group):
    """Turn expected runtime failures into a one-line error instead of a traceback."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except (BotoCoreError, ClientError, OSError, ValueError) as exc:
            _abort(str(exc))


@click.group(cls=_CliGroup)
@click.version_option(package_name="secretsync")
def cli():
    """secretsync — bidirectional .env ↔ AWS secrets sync."""


# ---------------------------------------------------------------------------
# diff / status (read-only)
# ---------------------------------------------------------------------------


@cli.command()
@_env_file_option
@_config_option
@_format_option
@_no_mask_option
def diff(env_file, config, output_format, mask):
    """Show differences between the local .env and the remote backend."""
    _warn_no_mask(mask)
    _check_env_file_path(env_file)
    cfg = _load_and_validate(config)
    backend = get_backend(cfg)

    local = parse_env_file(env_file)
    remote = backend.read()

    plan = build_sync_plan(
        local,
        remote,
        direction=SyncDirection.PUSH,
        backend_type=cfg.backend_type,
    )

    rendered = render_plan(plan, fmt=output_format, mask=mask)
    click.echo(rendered, nl=False)

    if not plan.has_changes:
        console.print("[bold green]No differences found.[/]")


@cli.command()
@_env_file_option
@_config_option
@_format_option
@_no_mask_option
def status(env_file, config, output_format, mask):
    """Alias for diff — show current sync status."""
    ctx = click.get_current_context()
    ctx.invoke(diff, env_file=env_file, config=config, output_format=output_format, mask=mask)


# ---------------------------------------------------------------------------
# push  (local → remote)
# ---------------------------------------------------------------------------


@cli.command()
@_env_file_option
@_config_option
@_dry_run_option
@_force_option
@_prune_option
@_format_option
@_no_mask_option
def push(env_file, config, dry_run, force, prune, output_format, mask):
    """Push local .env changes to the remote backend."""
    _warn_no_mask(mask)
    _check_env_file_path(env_file)
    cfg = _load_and_validate(config)
    backend = get_backend(cfg)

    if not Path(env_file).exists():
        _abort(f"Env file not found: {env_file!r}")

    local = parse_env_file(env_file)
    remote = backend.read()

    plan = build_sync_plan(
        local,
        remote,
        direction=SyncDirection.PUSH,
        backend_type=cfg.backend_type,
        dry_run=dry_run,
        prune=prune,
    )

    rendered = render_plan(plan, fmt=output_format, mask=mask)
    click.echo(rendered, nl=False)

    if not plan.has_changes:
        console.print("[bold green]Nothing to push — already in sync.[/]")
        return

    if dry_run:
        return

    if prune and not local:
        _abort(
            f"Refusing to --prune from an empty env file ({env_file!r}): "
            "this would delete every remote key."
        )

    # Warn about deletions
    if plan.has_deletions and not prune:
        console.print(
            "[yellow]Note:[/] Remote has keys not in your local .env. "
            "Use [bold]--prune[/] to delete them."
        )

    # Confirmation prompt (skipped with --force)
    if not force:
        change_count = len(plan.changes)
        if not Confirm.ask(
            f"Apply {change_count} change(s) to remote?", default=False, console=console
        ):
            console.print("Aborted.")
            return

    updates, deletes = remote_changes(plan)
    backend.apply(updates, deletes)
    console.print("[bold green]Push complete.[/]")


# ---------------------------------------------------------------------------
# pull  (remote → local)
# ---------------------------------------------------------------------------


@cli.command()
@_env_file_option
@_config_option
@_dry_run_option
@_force_option
@_prune_option
@_format_option
@_no_mask_option
def pull(env_file, config, dry_run, force, prune, output_format, mask):
    """Pull remote secrets into the local .env file."""
    _warn_no_mask(mask)
    _check_env_file_path(env_file)
    cfg = _load_and_validate(config)
    backend = get_backend(cfg)

    local = parse_env_file(env_file)
    remote = backend.read()

    if not remote:
        console.print("[yellow]Warning:[/] Remote backend returned no secrets.")

    plan = build_sync_plan(
        local,
        remote,
        direction=SyncDirection.PULL,
        backend_type=cfg.backend_type,
        dry_run=dry_run,
        prune=prune,
    )

    rendered = render_plan(plan, fmt=output_format, mask=mask)
    click.echo(rendered, nl=False)

    if not plan.has_changes:
        console.print("[bold green]Nothing to pull — already in sync.[/]")
        return

    if dry_run:
        return

    if prune and not remote:
        _abort(
            "Refusing to --prune from an empty remote: this would delete every "
            "local key. Check the configured secret name / path."
        )

    # Confirmation prompt (skipped with --force)
    if not force:
        change_count = len(plan.changes)
        if not Confirm.ask(
            f"Apply {change_count} change(s) to {escape(repr(env_file))}?",
            default=False,
            console=console,
        ):
            console.print("Aborted.")
            return

    target = apply_plan_to_local(plan)
    write_env_file(env_file, target, prune=prune)
    console.print(f"[bold green]Pull complete → {escape(env_file)}[/]")
