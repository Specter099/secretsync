# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

secretsync is a Python CLI tool that provides bidirectional sync between local `.env` files and AWS Secrets Manager or Parameter Store. Built with Click, boto3, and Rich, it supports push, pull, and diff operations with configurable backends via `.secretsync.toml`.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Common Commands

```
# CLI usage
.venv/bin/secretsync diff --env-file .env
.venv/bin/secretsync push --env-file .env --dry-run
.venv/bin/secretsync pull --env-file .env --dry-run
.venv/bin/secretsync push --env-file .env --force
.venv/bin/secretsync pull --env-file .env --force

# Run tests
.venv/bin/pytest

# Lint
.venv/bin/ruff check .

# Lint with auto-fix
.venv/bin/ruff check --fix .
```

## Directory Structure

```
secretsync/
  cli.py              # Click CLI entry point (diff, status, push, pull commands)
  config.py           # Config loading from .secretsync.toml
  models.py           # Data models (SyncDirection, etc.)
  differ.py           # Sync plan builder and applier
  env_file.py         # .env file parser and writer
  backends/
    base.py           # Abstract backend interface
    secrets_manager.py # AWS Secrets Manager backend
    parameter_store.py # AWS Parameter Store backend
  formatters/
    terminal.py       # Rich terminal output
    json_fmt.py       # JSON output formatter
tests/
  test_cli.py         # CLI integration tests
  test_backends.py    # Backend unit tests (uses moto)
  test_differ.py      # Sync plan logic tests
  test_env_file.py    # .env parser tests
```

## Architecture

Multi-module Click CLI application with a pluggable backend system. Configuration is loaded from `.secretsync.toml` (TOML format via `tomllib`). The CLI entry point is `secretsync.cli:cli`, installed as the `secretsync` console script.

Key abstractions:
- **Backends** (`backends/`): `SecretsManagerBackend` and `ParameterStoreBackend` implement a common `read()`/`write_all()` interface
- **Differ** (`differ.py`): Builds a `SyncPlan` comparing local and remote state, supports both push (local-to-remote) and pull (remote-to-local) directions
- **Config** (`config.py`): Loads `.secretsync.toml` with backend type, region, secret name, and path settings

## Testing

Tests use `pytest` with `moto` for mocking AWS services. Coverage is enabled by default (`--cov=secretsync --cov-report=term-missing`).

```
.venv/bin/pytest                    # Run all tests with coverage
.venv/bin/pytest tests/test_cli.py  # Run specific test file
.venv/bin/pytest -x                 # Stop on first failure
```

## Code Style

Ruff is configured with line-length 100, targeting Python 3.11. Rules: E, F, I, UP (pyflakes, pycodestyle, isort, pyupgrade).
