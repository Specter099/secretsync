"""AWS Secrets Manager backend — stores all env vars as a single JSON blob."""

from __future__ import annotations

import json
import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from .base import Backend, sanitize_keys

logger = logging.getLogger(__name__)


class SecretsManagerBackend(Backend):
    """Stores all key/value pairs as a JSON object in a single AWS secret.

    The secret value looks like::

        {"DB_HOST": "localhost", "DB_PASS": "s3cret", ...}

    Creating the secret on first push is handled automatically.
    """

    def __init__(self, secret_name: str, region: str = "us-east-1") -> None:
        self.secret_name = secret_name
        self.region = region
        self._client = boto3.client(
            "secretsmanager",
            region_name=region,
            verify=True,
            config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
        )

    # ------------------------------------------------------------------
    # Backend interface
    # ------------------------------------------------------------------

    def read(self) -> dict[str, str]:
        """Fetch the secret and parse it as JSON."""
        try:
            response = self._client.get_secret_value(SecretId=self.secret_name)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                logger.debug("Secret %r not found — treating as empty.", self.secret_name)
                return {}
            raise

        secret_string = response.get("SecretString", "{}")
        try:
            data = json.loads(secret_string)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Secret '{self.secret_name}' does not contain valid JSON. "
                "secretsync requires a JSON object secret."
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Secret '{self.secret_name}' must be a JSON object (dict), "
                f"got {type(data).__name__}."
            )

        return sanitize_keys({k: str(v) for k, v in data.items()})

    def write(self, updates: dict[str, str]) -> None:
        """Merge *updates* into the existing secret (creates if absent)."""
        current = self.read()
        merged = {**current, **updates}
        self._put_secret(merged)

    def delete(self, keys: list[str]) -> None:
        """Remove *keys* from the JSON blob."""
        current = self.read()
        pruned = {k: v for k, v in current.items() if k not in keys}
        self._put_secret(pruned)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _put_secret(self, data: dict[str, str]) -> None:
        secret_string = json.dumps(data, indent=None, ensure_ascii=False)
        try:
            self._client.put_secret_value(
                SecretId=self.secret_name,
                SecretString=secret_string,
            )
            logger.debug("Updated secret %r (%d keys).", self.secret_name, len(data))
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                # Secret doesn't exist yet — create it
                self._client.create_secret(
                    Name=self.secret_name,
                    SecretString=secret_string,
                )
                logger.debug("Created secret %r (%d keys).", self.secret_name, len(data))
            else:
                raise
