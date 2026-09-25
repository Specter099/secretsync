"""AWS SSM Parameter Store backend — each env var is a separate SecureString parameter."""

from __future__ import annotations

import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from .base import Backend, sanitize_keys

logger = logging.getLogger(__name__)

_MAX_BATCH = 10  # DeleteParameters allows at most 10 names per call
_MAX_VALUE_BYTES = 4096  # Standard-tier parameter value limit


class ParameterStoreBackend(Backend):
    """Maps each env var to a separate SSM parameter under a common path prefix.

    For example, with ``path = "/myapp/prod/"``::

        DB_HOST  →  /myapp/prod/DB_HOST  (SecureString)
        DB_PASS  →  /myapp/prod/DB_PASS  (SecureString)
    """

    def __init__(self, path: str, region: str = "us-east-1") -> None:
        if not path.endswith("/"):
            path = path + "/"
        self.path = path
        self.region = region
        self._client = boto3.client(
            "ssm",
            region_name=region,
            verify=True,
            config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
        )

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    def read(self) -> dict[str, str]:
        """Fetch all parameters under :attr:`path` using recursive GetParametersByPath."""
        result: dict[str, str] = {}
        paginator = self._client.get_paginator("get_parameters_by_path")
        pages = paginator.paginate(
            Path=self.path,
            Recursive=False,
            WithDecryption=True,
        )
        for page in pages:
            for param in page.get("Parameters", []):
                name: str = param["Name"]
                key = name[len(self.path) :]  # strip prefix
                result[key] = param["Value"]
        return sanitize_keys(result)

    def write(self, updates: dict[str, str]) -> None:
        """Put each key as a SecureString parameter.

        All values are validated first so an invalid one can't leave a
        half-applied push behind.
        """
        problems = [
            f"{key}: empty values are not allowed by Parameter Store"
            for key, value in updates.items()
            if not value
        ] + [
            f"{key}: value is {len(value.encode())} bytes (limit {_MAX_VALUE_BYTES})"
            for key, value in updates.items()
            if len(value.encode()) > _MAX_VALUE_BYTES
        ]
        if problems:
            raise ValueError(
                "Cannot write to Parameter Store; nothing was written:\n  " + "\n  ".join(problems)
            )
        for key, value in updates.items():
            full_name = f"{self.path}{key}"
            try:
                self._client.put_parameter(
                    Name=full_name,
                    Value=value,
                    Type="SecureString",
                    Overwrite=True,
                )
                logger.debug("Wrote parameter %r.", full_name)
            except ClientError:
                logger.error("Failed to write parameter %r.", full_name)
                raise

    def delete(self, keys: list[str]) -> None:
        """Delete parameters for the given keys in batches of 10."""
        names = [f"{self.path}{k}" for k in keys]
        for i in range(0, len(names), _MAX_BATCH):
            batch = names[i : i + _MAX_BATCH]
            try:
                self._client.delete_parameters(Names=batch)
                logger.debug("Deleted parameters: %s", batch)
            except ClientError:
                logger.error("Failed to delete parameters: %s", batch)
                raise
