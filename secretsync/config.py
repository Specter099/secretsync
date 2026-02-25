"""Load secretsync configuration from .secretsync.toml and environment variables."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


DEFAULT_CONFIG_FILE = ".secretsync.toml"
DEFAULT_BACKEND = "secrets_manager"
DEFAULT_REGION = "us-east-1"


@dataclass
class SecretsManagerConfig:
    secret_name: str = ""


@dataclass
class ParameterStoreConfig:
    path: str = "/"


@dataclass
class Config:
    """Resolved secretsync configuration."""

    backend_type: str = DEFAULT_BACKEND
    region: str = DEFAULT_REGION
    secrets_manager: SecretsManagerConfig = field(default_factory=SecretsManagerConfig)
    parameter_store: ParameterStoreConfig = field(default_factory=ParameterStoreConfig)

    # Runtime options (not from file — set by CLI flags)
    env_file: str = ".env"
    dry_run: bool = False
    force: bool = False
    prune: bool = False
    mask: bool = True
    output_format: str = "table"  # "table" | "json"


def load_config(
    config_path: Optional[str | Path] = None,
    *,
    env_file: str = ".env",
    dry_run: bool = False,
    force: bool = False,
    prune: bool = False,
    mask: bool = True,
    output_format: str = "table",
) -> Config:
    """Load configuration in priority order:

    1. CLI flags (passed as keyword args)
    2. Environment variables
    3. `.secretsync.toml` file
    4. Built-in defaults
    """
    cfg = Config(
        env_file=env_file,
        dry_run=dry_run,
        force=force,
        prune=prune,
        mask=mask,
        output_format=output_format,
    )

    # --- Load from TOML file ---
    path = Path(config_path or DEFAULT_CONFIG_FILE)
    if path.exists():
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        backend_section = raw.get("backend", {})
        cfg.backend_type = backend_section.get("type", DEFAULT_BACKEND)
        cfg.region = backend_section.get("region", DEFAULT_REGION)

        sm = raw.get("secrets_manager", {})
        cfg.secrets_manager.secret_name = sm.get("secret_name", "")

        ps = raw.get("parameter_store", {})
        cfg.parameter_store.path = ps.get("path", "/")

    # --- Environment variable overrides ---
    if "SECRETSYNC_BACKEND" in os.environ:
        cfg.backend_type = os.environ["SECRETSYNC_BACKEND"]

    # AWS_REGION > SECRETSYNC_REGION
    for env_key in ("SECRETSYNC_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        if env_key in os.environ:
            cfg.region = os.environ[env_key]
            break

    if "SECRETSYNC_SECRET_NAME" in os.environ:
        cfg.secrets_manager.secret_name = os.environ["SECRETSYNC_SECRET_NAME"]

    if "SECRETSYNC_PARAMETER_PATH" in os.environ:
        cfg.parameter_store.path = os.environ["SECRETSYNC_PARAMETER_PATH"]

    return cfg


def validate_config(cfg: Config) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: list[str] = []

    valid_backends = {"secrets_manager", "parameter_store"}
    if cfg.backend_type not in valid_backends:
        errors.append(
            f"Invalid backend '{cfg.backend_type}'. "
            f"Must be one of: {', '.join(sorted(valid_backends))}"
        )

    if cfg.backend_type == "secrets_manager" and not cfg.secrets_manager.secret_name:
        errors.append(
            "secrets_manager.secret_name is required when backend type is 'secrets_manager'. "
            "Set it in .secretsync.toml or via SECRETSYNC_SECRET_NAME."
        )

    if cfg.backend_type == "parameter_store":
        p = cfg.parameter_store.path
        if not p or not p.startswith("/"):
            errors.append(
                "parameter_store.path must be an absolute path starting with '/'. "
                "Set it in .secretsync.toml or via SECRETSYNC_PARAMETER_PATH."
            )

    valid_formats = {"table", "json"}
    if cfg.output_format not in valid_formats:
        errors.append(
            f"Invalid output format '{cfg.output_format}'. "
            f"Must be one of: {', '.join(sorted(valid_formats))}"
        )

    return errors
