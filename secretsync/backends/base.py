"""Abstract base class for secretsync backends."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_VALID_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sanitize_keys(data: dict[str, str]) -> dict[str, str]:
    """Filter out keys that are not valid environment variable names.

    Valid keys match ``[A-Za-z_][A-Za-z0-9_]*``.  Invalid keys are logged
    and silently dropped to prevent .env injection.
    """
    clean: dict[str, str] = {}
    for key, value in data.items():
        if _VALID_ENV_KEY.match(key):
            clean[key] = value
        else:
            logger.warning("Skipping invalid env key from remote backend: %r", key)
    return clean


class Backend(ABC):
    """Interface all secretsync storage backends must implement."""

    @abstractmethod
    def read(self) -> dict[str, str]:
        """Fetch all key→value pairs from the remote backend.

        Returns:
            A flat dict of all secrets/parameters currently stored.
        """

    @abstractmethod
    def write(self, updates: dict[str, str]) -> None:
        """Persist *updates* to the remote backend.

        This is a **merge** operation — keys not present in *updates* are
        left untouched unless :meth:`delete` is called explicitly.

        Args:
            updates: Mapping of key→value pairs to write.
        """

    @abstractmethod
    def delete(self, keys: list[str]) -> None:
        """Remove the given *keys* from the remote backend.

        Args:
            keys: List of key names to delete.
        """

    def apply(self, updates: dict[str, str], deletes: list[str]) -> None:
        """Write *updates* and remove *deletes*; keys in neither are left untouched.

        Backends that can do both in one remote call should override this.
        """
        if updates:
            self.write(updates)
        if deletes:
            self.delete(deletes)
