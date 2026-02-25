# Security Audit Report — secretsync

**Date:** 2026-02-25
**Scope:** Full codebase review of `secretsync` v0.1.0
**Auditor:** Automated security review (Claude)

---

## Executive Summary

`secretsync` is a CLI tool that bidirectionally syncs `.env` files with AWS Secrets Manager and SSM Parameter Store. The codebase is compact (~700 LOC of application code) and generally well-structured. However, this audit identified **5 high-severity**, **4 medium-severity**, and **4 low-severity** findings that should be addressed before production use.

---

## Findings

### CRITICAL / HIGH Severity

#### H1. `.env` files written with world-readable permissions (0644)

**File:** `secretsync/env_file.py:164`
**Severity:** HIGH
**CWE:** CWE-732 (Incorrect Permission Assignment for Critical Resource)

`write_env_file()` uses `Path.write_text()` which creates files with the default umask (typically 0644). This means any user on the system can read secrets pulled from AWS.

**Recommendation:** Set file permissions to `0600` (owner read/write only) after writing:

```python
import os, stat

file_path.write_text(content, encoding="utf-8")
os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
```

Alternatively, open the file with restricted permissions from the start using `os.open()` with `O_CREAT | O_WRONLY` and mode `0o600`.

---

#### H2. No input validation on environment variable keys from remote backends

**File:** `secretsync/backends/secrets_manager.py:61`, `secretsync/backends/parameter_store.py:50-51`
**Severity:** HIGH
**CWE:** CWE-20 (Improper Input Validation)

Keys fetched from the remote backend are passed directly into `.env` file writes with no validation. A malicious or misconfigured secret could contain:

- Keys with newlines (`.env` injection): A key like `"LEGIT=safe\nMALICIOUS=payload"` would inject an extra line.
- Keys with shell metacharacters that, when sourced via `source .env` or `eval`, could trigger command execution.
- Parameter Store key stripping (`name[len(self.path):]`) does not validate the result is a safe env var name.

**Recommendation:** Validate that all keys match `^[A-Za-z_][A-Za-z0-9_]*$` before writing them locally. Reject or skip keys that don't conform:

```python
import re
_VALID_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def _validate_keys(data: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in data.items() if _VALID_KEY.match(k)}
```

---

#### H3. Secret values exposed in process memory and never cleared

**File:** All backend and differ modules
**Severity:** HIGH
**CWE:** CWE-316 (Cleartext Storage of Sensitive Information in Memory)

Secret values are stored as plain Python strings throughout the application lifecycle. Python strings are immutable and cannot be zeroed out, meaning secrets persist in process memory until garbage collected. While this is a common limitation in Python, it's worth noting for high-security environments.

**Recommendation:** This is difficult to fully mitigate in Python. For defense-in-depth:
- Minimize the lifetime of variables holding secret values.
- Avoid unnecessary copies of secret data.
- Consider using `bytearray` (which can be zeroed) for the most sensitive operations if feasible.
- Document this limitation for users in high-security contexts.

---

#### H4. `--no-mask` flag exposes all secrets to terminal and logs

**File:** `secretsync/cli.py:67-74`
**Severity:** HIGH
**CWE:** CWE-532 (Insertion of Sensitive Information into Log File)

The `--no-mask` flag renders all secret values in plaintext to stdout. If the terminal session is being logged (e.g., `script`, CI logs, shell history), secrets are permanently captured.

**Recommendation:**
- Print a warning when `--no-mask` is used: `"WARNING: Secret values will be displayed in plaintext."`
- Consider requiring `--no-mask` to be combined with `--force` or an explicit acknowledgment.
- Detect if stdout is being piped/redirected and warn accordingly.

---

#### H5. Race condition in `write_all()` — TOCTOU on prune

**File:** `secretsync/backends/base.py:38-51`
**Severity:** HIGH
**CWE:** CWE-367 (Time-of-Check Time-of-Use Race Condition)

The `write_all()` method calls `self.write(data)` then `self.read()` to find stale keys to delete. Between the write and the read, another process or user could have added new keys, which would then be incorrectly deleted by the prune operation.

```python
def write_all(self, data, *, prune=False):
    if data:
        self.write(data)        # step 1: write
    if prune:
        current = self.read()   # step 2: read (TOCTOU gap)
        stale = [k for k in current if k not in data]
        if stale:
            self.delete(stale)  # step 3: delete (may delete newly-added keys)
```

**Recommendation:**
- For Secrets Manager: read the current state *before* writing, compute the stale set, then write and delete atomically (or as close to it as possible).
- For Parameter Store: consider using SSM's `LabelParameterVersion` or versioning to prevent clobbering.
- At minimum, document this race condition for users who may run concurrent syncs.

---

### MEDIUM Severity

#### M1. No path traversal protection on `--env-file` argument

**File:** `secretsync/cli.py:27-33`
**Severity:** MEDIUM
**CWE:** CWE-22 (Improper Limitation of a Pathname to a Restricted Directory)

The `--env-file` path is passed directly to file I/O operations without any sanitization. A malicious or careless invocation could read/write arbitrary files:

```bash
secretsync pull --env-file /etc/passwd --force
secretsync pull --env-file ../../other-project/.env --force
```

**Recommendation:** Consider:
- Warning if the target path is outside the current working directory.
- Resolving the path and checking it doesn't escape a project root.
- At minimum, refusing absolute paths unless a `--allow-absolute-path` flag is set.

---

#### M2. TOML config file loaded without size limits

**File:** `secretsync/config.py:78-79`
**Severity:** MEDIUM
**CWE:** CWE-400 (Uncontrolled Resource Consumption)

The TOML configuration file is loaded entirely into memory with `path.read_text()`. A malicious `.secretsync.toml` (e.g., placed via symlink or committed to a shared repo) could be extremely large and cause memory exhaustion.

**Recommendation:** Check file size before reading:

```python
if path.stat().st_size > 1_000_000:  # 1 MB sanity limit
    raise ValueError("Config file is suspiciously large")
```

---

#### M3. Secrets Manager backend stores all secrets in a single JSON blob

**File:** `secretsync/backends/secrets_manager.py`
**Severity:** MEDIUM
**CWE:** CWE-311 (Missing Encryption of Sensitive Data) — partial

All secrets are stored as a single JSON object. This means:
- **Blast radius:** Any IAM principal with `secretsmanager:GetSecretValue` on this secret gets *all* environment variables.
- **Size limit:** AWS Secrets Manager has a 64 KB secret size limit. Large environments will silently truncate.
- **Audit granularity:** CloudTrail logs access at the secret level, not per-key. You can't tell which specific variable was accessed.

**Recommendation:**
- Document the 64 KB limit and validate the serialized JSON size before writing.
- Consider offering a mode where each key is stored as a separate secret (similar to Parameter Store).
- Document IAM permission implications for users.

---

#### M4. No TLS certificate verification configuration

**File:** `secretsync/backends/secrets_manager.py:29`, `secretsync/backends/parameter_store.py:32`
**Severity:** MEDIUM
**CWE:** CWE-295 (Improper Certificate Validation)

The `boto3` clients are created with default settings. While boto3 uses TLS by default and verifies certificates, there is no explicit enforcement or configuration option to:
- Pin specific CA bundles.
- Set a custom endpoint URL (which could be used to redirect traffic to a MITM proxy).
- Disable TLS (a `verify=False` could be injected via `AWS_CA_BUNDLE` env var set to something invalid, or `REQUESTS_CA_BUNDLE`).

**Recommendation:**
- Explicitly set `verify=True` when creating boto3 clients.
- Warn if `AWS_CA_BUNDLE` or `REQUESTS_CA_BUNDLE` environment variables are set.
- Consider logging the endpoint URL being used.

---

### LOW Severity

#### L1. No `.env` backup before overwriting on `pull`

**File:** `secretsync/cli.py:283-284`, `secretsync/env_file.py:120-164`
**Severity:** LOW
**CWE:** CWE-252 (Unchecked Return Value) — related

When pulling secrets, the local `.env` file is overwritten in place. If the write fails partway through (disk full, permission error), the original file contents are lost.

**Recommendation:** Write to a temporary file first, then atomically rename:

```python
import tempfile

tmp = file_path.with_suffix(".env.tmp")
tmp.write_text(content, encoding="utf-8")
tmp.rename(file_path)
```

---

#### L2. CI workflow uses hardcoded AWS credentials

**File:** `.github/workflows/ci.yml:38-41`
**Severity:** LOW (test-only)

```yaml
AWS_ACCESS_KEY_ID: testing
AWS_SECRET_ACCESS_KEY: testing
```

While these are dummy credentials for moto, this pattern normalizes hardcoded credentials in CI configs. If a developer copies this pattern with real credentials, it becomes a critical leak.

**Recommendation:**
- Add a comment: `# Dummy credentials for moto mock — never use real credentials here`
- Consider using `MOTO_ALLOW_NONEXISTENT_REGION` or similar moto-specific env vars instead.

---

#### L3. Sensitive key detection heuristic is overly broad

**File:** `secretsync/differ.py:9-22`
**Severity:** LOW
**CWE:** CWE-200 (Exposure of Sensitive Information)

The `_SENSITIVE_FRAGMENTS` list includes "key" which matches non-sensitive variables like `CACHE_KEY_PREFIX`, `KEYBOARD_LAYOUT`, etc. Conversely, it misses common patterns like `CONNECTION_STRING`, `DSN`, `DATABASE_URL`, `ENCRYPTION_IV`.

**Recommendation:** Refine the heuristic:
- Remove overly broad fragments like "key" (keep "api_key", "apikey", "private_key", "secret_key").
- Add: `"connection_string"`, `"dsn"`, `"database_url"`, `"_url"` (when also containing auth fragments).
- Consider allowing users to configure sensitive key patterns in `.secretsync.toml`.

---

#### L4. No rate limiting or retry logic for AWS API calls

**File:** `secretsync/backends/secrets_manager.py`, `secretsync/backends/parameter_store.py`
**Severity:** LOW
**CWE:** CWE-770 (Allocation of Resources Without Limits or Throttling)

Neither backend implements retry logic with exponential backoff. AWS APIs have rate limits, and transient failures will cause the tool to crash rather than retry gracefully.

**Recommendation:** Configure boto3 retry behavior:

```python
from botocore.config import Config as BotoConfig

retry_config = BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"})
self._client = boto3.client("ssm", region_name=region, config=retry_config)
```

---

## Positive Findings

The audit also identified several good security practices already in place:

1. **No command injection vectors** — The codebase uses no `subprocess`, `os.system()`, `eval()`, or `exec()` calls.
2. **Good use of `tomllib`** — Safe TOML parser (no deserialization attacks like YAML's `!!python/object`).
3. **Input validation on config** — `validate_config()` properly checks backend types and required fields.
4. **`.env` in `.gitignore`** — Prevents accidental secret commits.
5. **Confirmation prompts** — Destructive operations require explicit user confirmation (skippable with `--force` for CI).
6. **Secrets masked by default** — The `--no-mask` flag must be explicitly provided to show values.
7. **Dry-run support** — All write operations support `--dry-run` for safe previewing.
8. **Strong test coverage** — All backends, CLI commands, and edge cases have test coverage with moto mocks.
9. **No pickle/YAML deserialization** — Avoids common Python deserialization vulnerabilities.
10. **SecureString for Parameter Store** — SSM parameters are correctly stored as `SecureString` type.

---

## Summary Matrix

| ID  | Severity | Finding                                          | Effort to Fix |
|-----|----------|--------------------------------------------------|---------------|
| H1  | HIGH     | .env written with world-readable permissions      | Low           |
| H2  | HIGH     | No key validation from remote backends            | Low           |
| H3  | HIGH     | Secrets in cleartext memory (Python limitation)   | Medium        |
| H4  | HIGH     | `--no-mask` exposes secrets without warning        | Low           |
| H5  | HIGH     | TOCTOU race in `write_all()` prune logic          | Medium        |
| M1  | MEDIUM   | No path traversal protection on `--env-file`      | Low           |
| M2  | MEDIUM   | Config file loaded without size limits             | Low           |
| M3  | MEDIUM   | All secrets in single JSON blob (blast radius)    | Medium        |
| M4  | MEDIUM   | No explicit TLS verification enforcement          | Low           |
| L1  | LOW      | No atomic write / backup for .env on pull         | Low           |
| L2  | LOW      | Hardcoded dummy AWS creds in CI without comment   | Trivial       |
| L3  | LOW      | Overly broad sensitive key heuristic              | Low           |
| L4  | LOW      | No retry/backoff on AWS API calls                 | Low           |

---

## Recommended Priority

1. **Immediate (before any production use):** H1, H2, H4
2. **Short-term:** H5, M1, L1, L4
3. **Medium-term:** M2, M3, M4, L2, L3
4. **Accepted risk (document):** H3
