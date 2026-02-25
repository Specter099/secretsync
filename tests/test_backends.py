"""Tests for secretsync backends — all AWS calls mocked with moto."""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from secretsync.backends.base import sanitize_keys
from secretsync.backends.parameter_store import ParameterStoreBackend
from secretsync.backends.secrets_manager import SecretsManagerBackend

REGION = "us-east-1"


# ---------------------------------------------------------------------------
# Secrets Manager
# ---------------------------------------------------------------------------


@pytest.fixture
def sm_backend():
    with mock_aws():
        yield SecretsManagerBackend(secret_name="myapp/test", region=REGION)


class TestSecretsManagerBackend:
    def test_read_nonexistent_returns_empty(self, sm_backend):
        assert sm_backend.read() == {}

    def test_write_creates_secret(self, sm_backend):
        sm_backend.write({"A": "1", "B": "2"})
        assert sm_backend.read() == {"A": "1", "B": "2"}

    def test_write_merges_with_existing(self, sm_backend):
        sm_backend.write({"A": "1"})
        sm_backend.write({"B": "2"})
        result = sm_backend.read()
        assert result == {"A": "1", "B": "2"}

    def test_write_updates_existing_key(self, sm_backend):
        sm_backend.write({"A": "old"})
        sm_backend.write({"A": "new"})
        assert sm_backend.read()["A"] == "new"

    def test_delete_removes_keys(self, sm_backend):
        sm_backend.write({"A": "1", "B": "2", "C": "3"})
        sm_backend.delete(["B", "C"])
        result = sm_backend.read()
        assert "B" not in result
        assert "C" not in result
        assert result["A"] == "1"

    def test_delete_nonexistent_key_is_noop(self, sm_backend):
        sm_backend.write({"A": "1"})
        sm_backend.delete(["NONEXISTENT"])
        assert sm_backend.read() == {"A": "1"}

    def test_write_all_no_prune(self, sm_backend):
        sm_backend.write({"A": "1", "B": "2"})
        sm_backend.write_all({"A": "99"}, prune=False)
        result = sm_backend.read()
        assert result["A"] == "99"
        assert result["B"] == "2"

    def test_write_all_with_prune(self, sm_backend):
        sm_backend.write({"A": "1", "B": "2"})
        sm_backend.write_all({"A": "99"}, prune=True)
        result = sm_backend.read()
        assert result == {"A": "99"}

    def test_invalid_json_secret_raises(self):
        with mock_aws():
            client = boto3.client("secretsmanager", region_name=REGION)
            client.create_secret(Name="bad/secret", SecretString="not-json")
            backend = SecretsManagerBackend(secret_name="bad/secret", region=REGION)
            with pytest.raises(ValueError, match="valid JSON"):
                backend.read()

    def test_non_dict_json_secret_raises(self):
        with mock_aws():
            client = boto3.client("secretsmanager", region_name=REGION)
            client.create_secret(Name="array/secret", SecretString='["a","b"]')
            backend = SecretsManagerBackend(secret_name="array/secret", region=REGION)
            with pytest.raises(ValueError, match="JSON object"):
                backend.read()

    def test_values_coerced_to_strings(self, sm_backend):
        # Manually store an integer value and confirm read returns strings
        client = boto3.client("secretsmanager", region_name=REGION)
        client.create_secret(
            Name="myapp/test",
            SecretString=json.dumps({"PORT": 5432}),
        )
        result = sm_backend.read()
        assert result["PORT"] == "5432"
        assert isinstance(result["PORT"], str)


# ---------------------------------------------------------------------------
# Parameter Store
# ---------------------------------------------------------------------------


@pytest.fixture
def ps_backend():
    with mock_aws():
        yield ParameterStoreBackend(path="/myapp/test/", region=REGION)


class TestParameterStoreBackend:
    def test_read_empty_path_returns_empty(self, ps_backend):
        assert ps_backend.read() == {}

    def test_write_creates_parameters(self, ps_backend):
        ps_backend.write({"DB_HOST": "localhost", "DB_PORT": "5432"})
        result = ps_backend.read()
        assert result == {"DB_HOST": "localhost", "DB_PORT": "5432"}

    def test_write_overwrites_existing(self, ps_backend):
        ps_backend.write({"A": "old"})
        ps_backend.write({"A": "new"})
        assert ps_backend.read()["A"] == "new"

    def test_delete_removes_parameters(self, ps_backend):
        ps_backend.write({"A": "1", "B": "2", "C": "3"})
        ps_backend.delete(["B"])
        result = ps_backend.read()
        assert "B" not in result
        assert result["A"] == "1"
        assert result["C"] == "3"

    def test_path_trailing_slash_normalised(self):
        with mock_aws():
            b1 = ParameterStoreBackend(path="/app/prod", region=REGION)
            b2 = ParameterStoreBackend(path="/app/prod/", region=REGION)
            assert b1.path == b2.path == "/app/prod/"

    def test_write_all_with_prune(self, ps_backend):
        ps_backend.write({"A": "1", "B": "2"})
        ps_backend.write_all({"A": "99"}, prune=True)
        result = ps_backend.read()
        assert result == {"A": "99"}

    def test_write_all_no_prune_keeps_extra(self, ps_backend):
        ps_backend.write({"A": "1", "B": "2"})
        ps_backend.write_all({"A": "99"}, prune=False)
        result = ps_backend.read()
        assert result["B"] == "2"

    def test_keys_are_stripped_of_path_prefix(self, ps_backend):
        ps_backend.write({"MY_KEY": "value"})
        result = ps_backend.read()
        assert "MY_KEY" in result
        assert "/myapp/test/MY_KEY" not in result


# ---------------------------------------------------------------------------
# Key sanitization
# ---------------------------------------------------------------------------


class TestSanitizeKeys:
    def test_valid_keys_pass_through(self):
        data = {"DB_HOST": "localhost", "API_KEY": "abc", "_PRIVATE": "x"}
        assert sanitize_keys(data) == data

    def test_invalid_keys_are_dropped(self):
        data = {"VALID": "ok", "invalid-key": "bad", "123START": "bad", "has space": "bad"}
        result = sanitize_keys(data)
        assert result == {"VALID": "ok"}

    def test_empty_key_dropped(self):
        data = {"": "value", "OK": "fine"}
        assert sanitize_keys(data) == {"OK": "fine"}

    def test_newline_in_key_dropped(self):
        data = {"LEGIT\nINJECTED": "payload", "SAFE": "ok"}
        assert sanitize_keys(data) == {"SAFE": "ok"}
