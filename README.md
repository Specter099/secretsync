# secretsync

Bidirectional sync between a local `.env` file and AWS Secrets Manager or SSM Parameter Store.

```
pip install secretsync
```

## Configure

Create `.secretsync.toml` (optional; every setting can also come from environment variables):

```toml
[backend]
type = "secrets_manager"   # or "parameter_store"
region = "us-east-1"

[secrets_manager]
secret_name = "myapp/prod"

# [parameter_store]
# path = "/myapp/prod/"
```

| Variable | Overrides |
|---|---|
| `SECRETSYNC_BACKEND` | `backend.type` |
| `SECRETSYNC_REGION`, `AWS_REGION`, `AWS_DEFAULT_REGION` | `backend.region` (first one set wins) |
| `SECRETSYNC_SECRET_NAME` | `secrets_manager.secret_name` |
| `SECRETSYNC_PARAMETER_PATH` | `parameter_store.path` |

Secrets Manager stores all keys as one JSON object; Parameter Store stores each key as a
`SecureString` under the path prefix. AWS credentials come from the standard boto3 chain.

## Use

```
secretsync diff                 # show differences (alias: status)
secretsync push [--prune]       # local → remote
secretsync pull [--prune]       # remote → local
```

Common options: `--env-file FILE` (default `.env`), `--config FILE`, `--dry-run`,
`--force` (skip the confirmation prompt), `--format table|json`, `--no-mask`.

## Safety behaviour

- **Values are masked in output by default.** `--no-mask` prints them in plaintext.
- **Push writes only added or changed keys.** Remote keys you don't have locally are left
  alone unless you pass `--prune`. In Secrets Manager, JSON keys that aren't valid env-var
  names (and non-string values) are never modified.
- **`--prune` refuses to run from an empty source** (an empty `.env` on push, an empty or
  missing remote on pull), since that would delete everything on the other side.
- **Pulled `.env` files are written atomically with mode `0600`**, and values are quoted
  so the file is safe to `source` from a POSIX shell (no `$(...)`, backtick or `;` execution).
- Remote keys that aren't valid env-var names are skipped on read.

## Development

```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check secretsync tests && ruff format --check secretsync tests
```

AWS is mocked with moto; no real credentials are needed.
