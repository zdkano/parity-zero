"""Tests for the parity-zero FastAPI ingestion API.

Validates:
  - Health check endpoint
  - Ingestion endpoint accepts valid ScanResult payloads
  - Ingestion endpoint rejects malformed payloads
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from schemas.findings import Category, Confidence, Severity


client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_payload(**overrides) -> dict:
    """Return a valid ingestion payload as a dict."""
    payload = {
        "repo": "acme/webapp",
        "pr_number": 10,
        "commit_sha": "abc1234",
        "ref": "feature/auth",
        "findings": [
            {
                "category": Category.AUTHENTICATION.value,
                "severity": Severity.HIGH.value,
                "confidence": Confidence.MEDIUM.value,
                "title": "Missing auth middleware",
                "description": "The /admin route is unprotected.",
                "file": "src/routes/admin.py",
                "start_line": 15,
            }
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Ingestion endpoint
# ---------------------------------------------------------------------------

class TestIngest:
    def test_valid_payload_accepted(self):
        resp = client.post("/ingest", json=_valid_payload())
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["findings_count"] == 1

    def test_empty_findings_accepted(self):
        resp = client.post("/ingest", json=_valid_payload(findings=[]))
        assert resp.status_code == 202
        assert resp.json()["findings_count"] == 0

    def test_missing_repo_rejected(self):
        payload = _valid_payload()
        del payload["repo"]
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_severity_rejected(self):
        payload = _valid_payload()
        payload["findings"][0]["severity"] = "critical"
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_missing_finding_title_rejected(self):
        payload = _valid_payload()
        payload["findings"][0]["title"] = ""
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_pr_number_rejected(self):
        resp = client.post("/ingest", json=_valid_payload(pr_number=0))
        assert resp.status_code == 422
