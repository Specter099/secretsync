"""Backend factory and exports."""

from __future__ import annotations

from ..config import Config
from .base import Backend
from .parameter_store import ParameterStoreBackend
from .secrets_manager import SecretsManagerBackend

__all__ = ["Backend", "SecretsManagerBackend", "ParameterStoreBackend", "get_backend"]


def get_backend(cfg: Config) -> Backend:
    """Return the appropriate backend instance for the given config."""
    if cfg.backend_type == "secrets_manager":
        if not cfg.secrets_manager.secret_name:
            raise ValueError(
                "secrets_manager.secret_name must be set to use the Secrets Manager backend."
            )
        return SecretsManagerBackend(
            secret_name=cfg.secrets_manager.secret_name,
            region=cfg.region,
        )
    elif cfg.backend_type == "parameter_store":
        return ParameterStoreBackend(
            path=cfg.parameter_store.path,
            region=cfg.region,
        )
    else:
        raise ValueError(f"Unknown backend type: {cfg.backend_type!r}")
