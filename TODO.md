# PyPI Publishing — Next Steps

## Status Summary

| Repo | PyPI Status | Notes |
|------|-------------|-------|
| aws-assume | ✅ Published | "File already exists" = already live at v0.1.0 |
| cdkdiff | ✅ Published | "File already exists" = already live at v0.1.0 |
| secretsync | ✅ Published | Live at v0.1.0 — released 2026-02-26 |
| iamwhy | ❌ Failing | Trusted publishing — PyPI pending publisher mismatch |
| ssmtree | ❌ Failing | Trusted publishing — PyPI pending publisher mismatch |
| stackdrift | ❌ Failing | Trusted publishing — PyPI pending publisher mismatch |

---

## Fix: iamwhy, ssmtree, stackdrift

### Root Cause
`invalid-publisher: Publisher with matching claims was not found`

The GitHub side is correct (OIDC token issued with `environment: pypi`).
The PyPI side is missing or misconfigured pending publishers.

### Step 1 — Fix PyPI pending publishers

Go to: **https://pypi.org/manage/account/publishing/**

Delete any existing pending publishers for these three projects, then re-add them with **exactly** these values (case-sensitive):

#### iamwhy
| Field | Value |
|-------|-------|
| PyPI project name | `iamwhy` |
| Owner | `Specter099` |
| Repository name | `iamwhy` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

#### ssmtree
| Field | Value |
|-------|-------|
| PyPI project name | `ssmtree` |
| Owner | `Specter099` |
| Repository name | `ssmtree` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

#### stackdrift
| Field | Value |
|-------|-------|
| PyPI project name | `stackdrift` |
| Owner | `Specter099` |
| Repository name | `stackdrift` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

### Step 2 — Re-trigger releases

Once PyPI pending publishers are confirmed, run:

```bash
for repo in iamwhy ssmtree stackdrift; do
  gh release delete v0.1.0 --repo Specter099/$repo --yes --cleanup-tag
  gh release create v0.1.0 --repo Specter099/$repo --title "v0.1.0" --notes "Initial release"
done
```

### Step 3 — Check status

```bash
for repo in iamwhy ssmtree stackdrift; do
  echo "=== $repo ==="
  gh run list --repo Specter099/$repo --workflow publish.yml --limit 1
done
```

---

## OIDC Claims (for reference)

The exact values GitHub sends to PyPI — your pending publisher must match these:

```
repository_owner:  Specter099       ← capital S, rest lowercase
repository:        iamwhy           ← (or ssmtree / stackdrift)
workflow_ref:      .github/workflows/publish.yml
environment:       pypi             ← all lowercase
```

---

## Other Pending Work

*(secretsync is now published — no further action needed)*
