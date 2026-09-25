"""AWS Secrets Manager backend — stores all env vars as a single JSON blob."""

from __future__ import annotations

import json
import logging

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from .base import Backend, sanitize_keys

logger = logging.getLogger(__name__)

_MAX_SECRET_BYTES = 65_536  # SecretString size limit


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
        """Fetch the secret as env vars: invalid keys dropped, values as strings.

        Non-string JSON values are rendered as JSON (``true``, ``null``, ``5432``).
        """
        data = self._read_raw()
        return sanitize_keys(
            {k: v if isinstance(v, str) else json.dumps(v) for k, v in data.items()}
        )

    def write(self, updates: dict[str, str]) -> None:
        """Merge *updates* into the existing secret (creates if absent)."""
        self.apply(updates, [])

    def delete(self, keys: list[str]) -> None:
        """Remove *keys* from the JSON blob."""
        self.apply({}, keys)

    def apply(self, updates: dict[str, str], deletes: list[str]) -> None:
        """Apply updates and deletes in a single secret version.

        Merges against the raw stored JSON so keys secretsync doesn't manage
        (non env-var names, non-string values) are preserved untouched.
        """
        if not updates and not deletes:
            return
        data = self._read_raw()
        data.update(updates)
        for key in deletes:
            data.pop(key, None)
        self._put_secret(data)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _read_raw(self) -> dict:
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

        return data

    def _put_secret(self, data: dict) -> None:
        secret_string = json.dumps(data, indent=None, ensure_ascii=False)
        size = len(secret_string.encode("utf-8"))
        if size > _MAX_SECRET_BYTES:
            raise ValueError(
                f"Secret '{self.secret_name}' would be {size} bytes, over the "
                f"{_MAX_SECRET_BYTES}-byte Secrets Manager limit. Nothing was written."
            )
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
