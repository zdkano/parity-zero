# Backend Getting Started

This document explains how to set up, run, and test the parity-zero backend locally.

## Overview

The parity-zero backend is a **thin authenticated API** that:

- Accepts structured review results from the GitHub Action reviewer
- Validates payloads against the ScanResult JSON contract
- Authenticates requests using a bearer token
- Persists results in a local SQLite database
- Provides minimal retrieval endpoints for debugging and validation

The backend is **not** a full control plane or dashboard. It is a minimal persistence layer that lays the foundation for future visibility and reporting features. See the [roadmap](.squad/context/roadmap.md) for what comes next.

## Storage

The backend uses **SQLite** for persistence.

**Why SQLite?**
- Zero external dependencies — uses Python's built-in `sqlite3` module
- No database server to install, configure, or maintain
- Works immediately on any developer machine
- Phase-appropriate simplicity — the backend needs local/dev usability, not production-scale analytics
- File-based — easy to inspect, back up, or reset

**Schema:**
- `runs` table — scan-level metadata (scan_id, repo, PR number, decision, risk score, timestamps) plus run summary metadata (provider status, concern/observation/note counts, changed/skipped file counts — ADR-036)
- `findings` table — individual findings linked to a run (category, severity, file, description)

**Database location:**
- Default: `parity_zero.db` in the working directory
- Override via `PARITY_ZERO_DB_PATH` environment variable

**Schema evolution:**
The SQLite store includes lightweight additive migration support. When an existing database is opened, any missing columns (e.g. run summary metadata added in ADR-036) are added automatically with safe defaults. This ensures databases created by earlier versions of parity-zero continue to work after upgrade without manual intervention. See ADR-037.

This is intentionally simple — column-presence detection and `ALTER TABLE ADD COLUMN` — not a full migration framework. A formal migration tool (e.g. Alembic) is deferred to later phases.

**Future evolution:**
Migration to Postgres or another relational store is expected as query, reporting, and multi-user needs grow. The current SQLite store is intentionally minimal. See ADR-035.

## Prerequisites

```bash
# Python 3.12+
python --version

# Install dependencies
pip install -r requirements.txt
```

No additional database installation is required — SQLite is included with Python.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `PARITY_ZERO_AUTH_TOKEN` | **Yes** | Bearer token for API authentication. All ingest and retrieval requests must include this token. |
| `PARITY_ZERO_DB_PATH` | No | Path to the SQLite database file. Default: `parity_zero.db` |

## Running the Backend

### 1. Set the auth token

```bash
export PARITY_ZERO_AUTH_TOKEN="your-secret-token-here"
```

Choose a strong, random token. For local development, any non-empty string works.

**Generate a random token:**

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Start the server

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The server starts at `http://localhost:8000`.

### 3. Verify health

```bash
curl http://localhost:8000/health
# → {"status":"ok"}
```

## Testing Ingest Locally

### Send a test scan result

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-token-here" \
  -d '{
    "repo": "acme/webapp",
    "pr_number": 42,
    "commit_sha": "abc1234",
    "ref": "feature/auth",
    "decision": "warn",
    "risk_score": 25,
    "findings": [
      {
        "category": "authentication",
        "severity": "high",
        "confidence": "medium",
        "title": "Missing auth middleware",
        "description": "The /admin route is unprotected.",
        "file": "src/routes/admin.py",
        "start_line": 15
      }
    ]
  }'
```

Expected response:

```json
{
  "status": "accepted",
  "scan_id": "<32-char-hex-id>",
  "decision": "warn",
  "risk_score": 25,
  "findings_count": 1
}
```

### Verify persisted runs

```bash
# List recent runs
curl -H "Authorization: Bearer your-secret-token-here" \
  http://localhost:8000/runs

# Get a specific run by scan_id
curl -H "Authorization: Bearer your-secret-token-here" \
  http://localhost:8000/runs/<scan_id>
```

## Connecting the GitHub Action

To wire the action to your backend, add these secrets/env vars to your workflow:

```yaml
env:
  PARITY_ZERO_API_URL: ${{ secrets.PARITY_ZERO_API_URL }}
  PARITY_ZERO_API_TOKEN: ${{ secrets.PARITY_ZERO_API_TOKEN }}
```

Or use the action inputs:

```yaml
- uses: zdkano/parity-zero@main
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    api_url: https://your-backend.example.com
    api_token: ${{ secrets.PARITY_ZERO_API_TOKEN }}
```

See [GitHub Action Setup](github-action-setup.md) for full workflow examples.

## Running Tests

```bash
# Run all backend tests
python -m pytest tests/test_api.py tests/test_persistence.py tests/test_auth.py tests/test_backend_ingest.py -v

# Run the full test suite
python -m pytest tests/ -v
```

All tests use in-memory SQLite — no database file is created during testing.

## Resetting the Database

To start fresh, delete the database file:

```bash
rm parity_zero.db
```

The schema is recreated automatically on next startup.

**Note:** Resetting is rarely needed. When upgrading parity-zero, the backend automatically migrates older databases to add any missing columns (ADR-037). Existing data is preserved with safe default values for new columns.

## What This Is Not

- **Not a production-hardened database** — SQLite is suitable for local/dev use and small-scale deployment. Migration to a richer store is planned.
- **Not a full control plane** — there is no dashboard, search, analytics, or reporting UI yet.
- **Not multi-user** — the auth model is a single shared bearer token, not user accounts or RBAC.
- **Not a findings authority** — persisting results does not change their trust semantics. Findings, concerns, and observations retain their original meaning. See [Trust Model](trust-model.md).

## What the Backend Stores

- **Per run:** scan_id, repo, PR number, commit SHA, ref, timestamp, decision, risk score, findings count, provider name, provider invocation status, provider gate decision, concerns count, observations count, provider notes count/suppressed count, changed/skipped files count, ingested_at
- **Per finding:** id, category, severity, confidence, title, description, file, start/end line, recommendation

The backend **does not** store full ReviewPlan, ReviewBundle, ReviewTrace entries, concern/observation text, provider note text, or markdown summaries. Only summary counts are persisted — see ADR-036 and [API Reference](api.md) for details.
