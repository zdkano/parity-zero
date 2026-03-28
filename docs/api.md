# API Reference

This document describes the parity-zero backend API — available endpoints, request/response shapes, authentication, and usage examples.

## Base URL

When running locally:

```
http://localhost:8000
```

## Authentication

All endpoints except `/health` require bearer token authentication.

**Header format:**

```
Authorization: Bearer <token>
```

The token must match the `PARITY_ZERO_AUTH_TOKEN` environment variable configured on the server. Requests without a valid token receive a `401 Unauthorized` response.

**If the server token is not configured**, all authenticated requests are rejected with:

```json
{"detail": "Server auth token not configured (PARITY_ZERO_AUTH_TOKEN)."}
```

## Endpoints

### GET /health

Liveness check. No authentication required.

**Response:**

```json
{"status": "ok"}
```

**Status codes:**
- `200` — server is running

---

### POST /ingest

Receive and persist a scan result from the reviewer.

**Authentication:** Required

**Content-Type:** `application/json`

**Request body:** A valid `ScanResult` JSON payload. See [schemas/findings.py](../schemas/findings.py) for the full schema.

The endpoint also accepts optional **run summary metadata** alongside the ScanResult fields. These extra fields are not part of the ScanResult contract but are persisted for debugging and history. See ADR-036.

**Required fields:**

| Field | Type | Description |
|---|---|---|
| `repo` | string | Repository identifier (e.g. `"acme/webapp"`) |
| `pr_number` | integer (≥ 1) | Pull request number |
| `commit_sha` | string (7–40 chars) | Head commit SHA |
| `ref` | string | Head branch ref |
| `findings` | array | List of Finding objects (can be empty) |

**Optional fields:**

| Field | Type | Default | Description |
|---|---|---|---|
| `scan_id` | string | Auto-generated (32-char hex) | Unique scan identifier |
| `decision` | string | `"pass"` | `"pass"`, `"warn"`, or `"block"` |
| `risk_score` | integer (0–100) | `0` | Aggregate risk score |
| `timestamp` | ISO 8601 datetime | Auto-generated | Scan timestamp |

**Run summary metadata fields (optional, persisted for debugging/history — ADR-036):**

| Field | Type | Default | Description |
|---|---|---|---|
| `provider_name` | string | `""` | Reasoning provider used (e.g. `"github-models"`, `"anthropic"`) |
| `provider_invoked` | boolean | `false` | Whether the reasoning provider was actually invoked |
| `provider_gate_decision` | string | `""` | Gate outcome: `"invoked"`, `"skipped"`, `"disabled"`, `"unavailable"` |
| `concerns_count` | integer | `0` | Number of ReviewConcern instances generated |
| `observations_count` | integer | `0` | Number of ReviewObservation instances generated |
| `provider_notes_count` | integer | `0` | Raw candidate notes returned by provider |
| `provider_notes_suppressed_count` | integer | `0` | Provider notes suppressed by overlap filtering |
| `changed_files_count` | integer | `0` | Total changed files discovered in the PR |
| `skipped_files_count` | integer | `0` | Changed files whose content could not be loaded (deleted, binary, too large, unreadable) |

These fields are **not part of the ScanResult JSON contract**. They are accepted alongside the ScanResult fields and persisted in the `runs` table for operational visibility. The reviewer action populates them automatically when sending results to the backend.

**Finding fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `category` | string | Yes | `authentication`, `authorization`, `input_validation`, `secrets`, `insecure_configuration`, `dependency_risk` |
| `severity` | string | Yes | `high`, `medium`, `low` |
| `confidence` | string | Yes | `high`, `medium`, `low` |
| `title` | string (1–256 chars) | Yes | Finding title |
| `description` | string (≥ 1 char) | Yes | Finding description |
| `file` | string | Yes | File path relative to repo root |
| `start_line` | integer (≥ 1) | No | Start line number |
| `end_line` | integer (≥ 1) | No | End line number |
| `recommendation` | string | No | Actionable guidance |

**Example request:**

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-token" \
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

**Success response (202 Accepted):**

```json
{
  "status": "accepted",
  "scan_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "decision": "warn",
  "risk_score": 25,
  "findings_count": 1
}
```

**Status codes:**
- `202` — accepted and persisted
- `401` — missing or invalid authentication token
- `422` — payload validation failed (malformed JSON, missing required fields, invalid enum values, etc.)

---

### GET /runs

List recent scan runs.

**Authentication:** Required

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `repo` | string | None | Filter by repository (exact match) |
| `limit` | integer (1–100) | 20 | Maximum results |
| `offset` | integer (≥ 0) | 0 | Pagination offset |

**Example requests:**

```bash
# List recent runs
curl -H "Authorization: Bearer your-token" \
  http://localhost:8000/runs

# Filter by repo
curl -H "Authorization: Bearer your-token" \
  "http://localhost:8000/runs?repo=acme/webapp"

# Paginate
curl -H "Authorization: Bearer your-token" \
  "http://localhost:8000/runs?limit=10&offset=20"
```

**Response:**

```json
{
  "runs": [
    {
      "scan_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
      "repo": "acme/webapp",
      "pr_number": 42,
      "commit_sha": "abc1234",
      "ref": "feature/auth",
      "timestamp": "2026-03-28T12:00:00+00:00",
      "decision": "warn",
      "risk_score": 25,
      "findings_count": 1,
      "provider_name": "github-models",
      "provider_invoked": 1,
      "provider_gate_decision": "invoked",
      "concerns_count": 2,
      "observations_count": 3,
      "provider_notes_count": 5,
      "provider_notes_suppressed_count": 1,
      "changed_files_count": 8,
      "skipped_files_count": 0,
      "ingested_at": "2026-03-28T12:00:01+00:00"
    }
  ],
  "count": 1
}
```

**Note:** Run listings do not include findings. Use `GET /runs/{scan_id}` for full detail.

**Status codes:**
- `200` — success
- `401` — missing or invalid authentication token

---

### GET /runs/{scan_id}

Retrieve a single run by scan_id, including its findings.

**Authentication:** Required

**Example request:**

```bash
curl -H "Authorization: Bearer your-token" \
  http://localhost:8000/runs/a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4
```

**Response:**

```json
{
  "scan_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
  "repo": "acme/webapp",
  "pr_number": 42,
  "commit_sha": "abc1234",
  "ref": "feature/auth",
  "timestamp": "2026-03-28T12:00:00+00:00",
  "decision": "warn",
  "risk_score": 25,
  "findings_count": 1,
  "provider_name": "github-models",
  "provider_invoked": 1,
  "provider_gate_decision": "invoked",
  "concerns_count": 2,
  "observations_count": 3,
  "provider_notes_count": 5,
  "provider_notes_suppressed_count": 1,
  "changed_files_count": 8,
  "skipped_files_count": 0,
  "ingested_at": "2026-03-28T12:00:01+00:00",
  "findings": [
    {
      "id": "f001",
      "scan_id": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
      "category": "authentication",
      "severity": "high",
      "confidence": "medium",
      "title": "Missing auth middleware",
      "description": "The /admin route is unprotected.",
      "file": "src/routes/admin.py",
      "start_line": 15,
      "end_line": null,
      "recommendation": null
    }
  ]
}
```

**Status codes:**
- `200` — success
- `401` — missing or invalid authentication token
- `404` — run not found

---

## Common Failure Cases

| Scenario | HTTP Status | Response |
|---|---|---|
| No `Authorization` header | 401 | `{"detail": "Missing Authorization header."}` |
| Wrong token | 401 | `{"detail": "Invalid authentication token."}` |
| Server token not configured | 401 | `{"detail": "Server auth token not configured (PARITY_ZERO_AUTH_TOKEN)."}` |
| Missing required field | 422 | Pydantic validation error with field details |
| Invalid enum value | 422 | Pydantic validation error with allowed values |
| Invalid JSON body | 422 | JSON parse error |
| Run not found | 404 | `{"detail": "Run not found."}` |

## What the Backend Stores Today

Per run (in the `runs` table):
- **Core ScanResult fields** — scan_id, repo, pr_number, commit_sha, ref, timestamp, decision, risk_score, findings_count
- **Run summary metadata (ADR-036)** — provider_name, provider_invoked, provider_gate_decision, concerns_count, observations_count, provider_notes_count, provider_notes_suppressed_count, changed_files_count, skipped_files_count
- **Ingest timestamp** — ingested_at

Per finding (in the `findings` table):
- id, scan_id, category, severity, confidence, title, description, file, start_line, end_line, recommendation

## What the Backend Intentionally Does NOT Store

- **Full ReviewPlan** — internal planning structure, not persisted
- **Full ReviewBundle** — internal evidence aggregation, not persisted
- **Full ReviewTrace entries** — internal trace log entries, not persisted
- **Full concern/observation text** — only counts are stored, not content
- **Provider candidate note text** — only counts are stored, not content
- **Skipped-file details per file** — only the total count is stored, not per-file path/reason
- **Review memory** — memory models exist but persistence is deferred
- **Markdown summary** — produced at runtime, not stored

Storing summary counts (not full objects) provides enough for debugging, history, and tuning without over-building persistence. Full internal reviewer object storage is deferred to later control-plane phases.

## What This API Is

- A thin ingest and retrieval endpoint for reviewer results
- Authenticated via a shared bearer token
- Backed by SQLite for local/dev simplicity
- Suitable for local development, CI integration testing, and small-scale deployment

## What This API Is Not

- Not a full search or analytics API — no full-text search, aggregation, or trend analysis
- Not a multi-tenant platform — single shared token, no user accounts
- Not production-hardened — SQLite is single-writer, no connection pooling, no migrations framework
- Not a dashboard backend — no chart data, no UI endpoints
- Not an authority on findings — persisting results does not change their trust semantics

These capabilities are intentionally deferred to later phases.
