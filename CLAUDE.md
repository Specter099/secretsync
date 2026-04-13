# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bidirectional sync between local `.env` files and AWS Secrets Manager / Parameter Store. CLI built with Click and Rich, packaged as `secretsync` on PyPI. Supports push, pull, and diff operations with dry-run, pruning, and JSON output.

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Common Commands

```
# Run tests (moto mocks AWS — no real credentials needed)
.venv/bin/pytest

# Run tests with verbose output
.venv/bin/pytest -v

# Lint
.venv/bin/ruff check secretsync tests

# Format check
.venv/bin/ruff format --check secretsync tests

# CLI usage
secretsync push --env-file .env --config .secretsync.toml --force
secretsync pull --env-file .env --config .secretsync.toml --force
secretsync diff --env-file .env --config .secretsync.toml
secretsync status --env-file .env --config .secretsync.toml
```

## Directory Structure

```
secretsync/
├── cli.py              # Click CLI entry point (push, pull, diff, status)
├── backends/
│   ├── base.py         # Backend ABC + key sanitization
│   ├── secrets_manager.py  # AWS Secrets Manager backend
│   └── parameter_store.py  # AWS SSM Parameter Store backend
├── differ.py           # Diff computation, sync plans, sensitivity detection
├── env_file.py         # .env file parsing and atomic writing
└── models.py           # Data models (DiffStatus, SyncDirection, SyncPlan)
tests/
├── test_backends.py    # Backend read/write/delete with moto mocks
├── test_cli.py         # CLI integration tests via Click's CliRunner
├── test_differ.py      # Diff and sync plan logic
└── test_env_file.py    # .env parsing, writing, permissions
```

## Architecture

- **Configuration**: `.secretsync.toml` specifies backend type (`secrets_manager` or `parameter_store`), region, and backend-specific settings (`secret_name` or `path`)
- **Backends**: Abstract base with `read()`, `write()`, `delete()`, `write_all(prune)` interface. Secrets Manager stores all keys as a single JSON object; Parameter Store stores each key as an individual parameter under a path prefix
- **Diff engine**: `compute_diff()` produces `DiffEntry` list, `build_sync_plan()` wraps with direction and prune semantics, `apply_plan_to_remote/local()` materializes the plan
- **Env file writer**: Atomic writes via temp file + rename, sets `0600` permissions, preserves comments and blank lines on update

## Configuration

Config file: `.secretsync.toml`

```toml
[backend]
type = "secrets_manager"   # or "parameter_store"
region = "us-east-1"

[secrets_manager]
secret_name = "myapp/prod"

# OR for Parameter Store:
# [parameter_store]
# path = "/myapp/prod/"
```

## Testing

- **Framework**: pytest with pytest-cov
- **AWS mocking**: moto (`mock_aws` context manager) — no real AWS credentials required
- **Coverage**: automatic via `--cov=secretsync --cov-report=term-missing` (configured in pyproject.toml)
- **CI matrix**: Python 3.11 and 3.12

## Code Style

- **Linter/formatter**: ruff
- **Line length**: 100
- **Target**: Python 3.11+
- **Rules**: E, F, I (isort), UP (pyupgrade)
