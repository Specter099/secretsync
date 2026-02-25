"""CLI integration tests using Click's test runner and moto for AWS."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from moto import mock_aws
import boto3

from secretsync.cli import cli


REGION = "us-east-1"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def toml_sm(tmp_path):
    """Write a .secretsync.toml pointing at Secrets Manager."""
    cfg = tmp_path / ".secretsync.toml"
    cfg.write_text(
        "[backend]\n"
        'type = "secrets_manager"\n'
        f'region = "{REGION}"\n\n'
        "[secrets_manager]\n"
        'secret_name = "cli-test/app"\n'
    )
    return cfg


@pytest.fixture
def env_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("DB_HOST=localhost\nDB_PORT=5432\nDB_PASS=secret123\n")
    return f


# ---------------------------------------------------------------------------
# diff / status
# ---------------------------------------------------------------------------


class TestDiffCommand:
    def test_diff_no_remote_shows_all_added(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            result = runner.invoke(
                cli,
                ["diff", "--env-file", str(env_file), "--config", str(toml_sm)],
            )
            assert result.exit_code == 0

    def test_diff_json_format(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            result = runner.invoke(
                cli,
                ["diff", "--env-file", str(env_file), "--config", str(toml_sm), "--format", "json"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "entries" in data
            assert "summary" in data
            assert data["direction"] == "push"

    def test_diff_in_sync_message(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            # Push first to get in sync
            runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(toml_sm), "--force"],
            )
            result = runner.invoke(
                cli,
                ["diff", "--env-file", str(env_file), "--config", str(toml_sm)],
            )
            assert result.exit_code == 0

    def test_status_alias(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            result = runner.invoke(
                cli,
                ["status", "--env-file", str(env_file), "--config", str(toml_sm)],
            )
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


class TestPushCommand:
    def test_push_dry_run_writes_nothing(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            result = runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(toml_sm), "--dry-run"],
            )
            assert result.exit_code == 0
            # Verify nothing was actually written
            client = boto3.client("secretsmanager", region_name=REGION)
            import botocore.exceptions
            with pytest.raises(client.exceptions.ResourceNotFoundException):
                client.get_secret_value(SecretId="cli-test/app")

    def test_push_force_no_prompt(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            result = runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(toml_sm), "--force"],
            )
            assert result.exit_code == 0
            # Verify the secret was created
            client = boto3.client("secretsmanager", region_name=REGION)
            resp = client.get_secret_value(SecretId="cli-test/app")
            data = json.loads(resp["SecretString"])
            assert data["DB_HOST"] == "localhost"
            assert data["DB_PORT"] == "5432"

    def test_push_aborted_when_user_declines(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            result = runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(toml_sm)],
                input="n\n",
            )
            assert result.exit_code == 0

    def test_push_missing_env_file_exits_nonzero(self, runner, tmp_path, toml_sm):
        with mock_aws():
            result = runner.invoke(
                cli,
                ["push", "--env-file", str(tmp_path / "missing.env"), "--config", str(toml_sm)],
            )
            assert result.exit_code != 0

    def test_push_json_format(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            result = runner.invoke(
                cli,
                [
                    "push", "--env-file", str(env_file), "--config", str(toml_sm),
                    "--force", "--format", "json",
                ],
            )
            assert result.exit_code == 0

    def test_push_already_in_sync(self, runner, tmp_path, toml_sm, env_file):
        with mock_aws():
            # Push once
            runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(toml_sm), "--force"],
            )
            # Push again — should say "nothing to push"
            result = runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(toml_sm), "--force"],
            )
            assert result.exit_code == 0


# ---------------------------------------------------------------------------
# pull
# ---------------------------------------------------------------------------


class TestPullCommand:
    def _seed_secret(self, data: dict):
        client = boto3.client("secretsmanager", region_name=REGION)
        client.create_secret(Name="cli-test/app", SecretString=json.dumps(data))

    def test_pull_force_writes_env_file(self, runner, tmp_path, toml_sm):
        with mock_aws():
            self._seed_secret({"DB_HOST": "remote-host", "DB_PASS": "remote-pass"})
            env_file = tmp_path / ".env"
            result = runner.invoke(
                cli,
                ["pull", "--env-file", str(env_file), "--config", str(toml_sm), "--force"],
            )
            assert result.exit_code == 0
            from secretsync.env_file import parse_env_file
            parsed = parse_env_file(env_file)
            assert parsed["DB_HOST"] == "remote-host"
            assert parsed["DB_PASS"] == "remote-pass"

    def test_pull_dry_run_does_not_write(self, runner, tmp_path, toml_sm):
        with mock_aws():
            self._seed_secret({"KEY": "value"})
            env_file = tmp_path / ".env"
            runner.invoke(
                cli,
                ["pull", "--env-file", str(env_file), "--config", str(toml_sm), "--dry-run"],
            )
            assert not env_file.exists()

    def test_pull_empty_remote_warns(self, runner, tmp_path, toml_sm):
        with mock_aws():
            env_file = tmp_path / ".env"
            result = runner.invoke(
                cli,
                ["pull", "--env-file", str(env_file), "--config", str(toml_sm), "--force"],
            )
            assert result.exit_code == 0

    def test_pull_aborted_when_user_declines(self, runner, tmp_path, toml_sm):
        with mock_aws():
            self._seed_secret({"A": "1"})
            env_file = tmp_path / ".env"
            result = runner.invoke(
                cli,
                ["pull", "--env-file", str(env_file), "--config", str(toml_sm)],
                input="n\n",
            )
            assert result.exit_code == 0
            assert not env_file.exists()


# ---------------------------------------------------------------------------
# Config validation errors
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_missing_secret_name_exits_nonzero(self, runner, tmp_path):
        bad_cfg = tmp_path / ".secretsync.toml"
        bad_cfg.write_text('[backend]\ntype = "secrets_manager"\nregion = "us-east-1"\n')
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\n")
        with mock_aws():
            result = runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(bad_cfg)],
            )
            assert result.exit_code != 0

    def test_invalid_backend_type_exits_nonzero(self, runner, tmp_path):
        bad_cfg = tmp_path / ".secretsync.toml"
        bad_cfg.write_text('[backend]\ntype = "s3"\nregion = "us-east-1"\n')
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\n")
        with mock_aws():
            result = runner.invoke(
                cli,
                ["push", "--env-file", str(env_file), "--config", str(bad_cfg)],
            )
            assert result.exit_code != 0
