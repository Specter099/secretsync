# secretsync Implementation Checklist

## Phase 1 — Project Scaffolding
- [x] Create directory structure
- [x] `pyproject.toml` with dependencies and CLI entry point
- [x] `.gitignore`
- [x] `tasks/todo.md` (this file)

## Phase 2 — Core Data Layer
- [x] `secretsync/models.py` — `EnvVar`, `DiffEntry`, `SyncPlan` dataclasses
- [x] `secretsync/env_file.py` — parse/write `.env` files preserving comments & blank lines
- [x] `secretsync/config.py` — load `.secretsync.toml` + env var overrides

## Phase 3 — Backends
- [x] `secretsync/backends/base.py` — `Backend` abstract base class
- [x] `secretsync/backends/secrets_manager.py` — AWS Secrets Manager (JSON blob)
- [x] `secretsync/backends/parameter_store.py` — AWS SSM Parameter Store (path-based)
- [x] `secretsync/backends/__init__.py` — factory `get_backend(config)`

## Phase 4 — Diff & Format
- [x] `secretsync/differ.py` — compute diff, mask sensitive values
- [x] `secretsync/formatters/terminal.py` — Rich table output
- [x] `secretsync/formatters/json_fmt.py` — machine-readable JSON output
- [x] `secretsync/formatters/__init__.py`

## Phase 5 — CLI
- [x] `secretsync/cli.py` — Click commands: push, pull, diff, status

## Phase 6 — Tests
- [x] `tests/test_env_file.py` — parsing edge cases, write round-trip
- [x] `tests/test_differ.py` — diff logic, masking
- [x] `tests/test_backends.py` — Secrets Manager + Parameter Store via moto
- [x] `tests/test_cli.py` — CLI integration via Click test runner

## Phase 7 — CI/CD
- [x] `.github/workflows/ci.yml` — lint + test on PRs and pushes

---

## CLI Interface Reference

```
secretsync push   [--env-file .env] [--dry-run] [--force] [--prune] [--format table|json]
secretsync pull   [--env-file .env] [--dry-run] [--force] [--format table|json]
secretsync diff   [--env-file .env] [--format table|json]
secretsync status [--env-file .env] [--format table|json]
```

## Config File Reference (`.secretsync.toml`)

```toml
[backend]
type = "secrets_manager"   # or "parameter_store"
region = "us-east-1"

[secrets_manager]
secret_name = "myapp/production"

[parameter_store]
path = "/myapp/production/"
```

Env var overrides: `SECRETSYNC_BACKEND`, `SECRETSYNC_REGION`, `AWS_REGION`.
