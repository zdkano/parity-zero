"""Tests for the parity-zero FastAPI ingestion API.

Validates:
  - Health check endpoint
  - Ingestion endpoint accepts valid ScanResult payloads
  - Ingestion endpoint rejects malformed payloads
  - Ingestion response includes decision and risk_score
  - Serialized reviewer output is ingestion-compatible
"""

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from schemas.findings import Category, Confidence, Decision, ScanResult, Severity
from reviewer.action import mock_run


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
# Ingestion endpoint — valid payloads
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

    def test_response_includes_decision(self):
        resp = client.post(
            "/ingest",
            json=_valid_payload(decision=Decision.WARN.value),
        )
        assert resp.status_code == 202
        assert resp.json()["decision"] == "warn"

    def test_response_includes_risk_score(self):
        resp = client.post(
            "/ingest",
            json=_valid_payload(risk_score=42),
        )
        assert resp.status_code == 202
        assert resp.json()["risk_score"] == 42

    def test_response_includes_scan_id(self):
        resp = client.post("/ingest", json=_valid_payload())
        body = resp.json()
        assert "scan_id" in body
        assert isinstance(body["scan_id"], str)
        assert len(body["scan_id"]) == 32


# ---------------------------------------------------------------------------
# Ingestion endpoint — rejected payloads
# ---------------------------------------------------------------------------

class TestIngestValidation:
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

    def test_invalid_category_rejected(self):
        payload = _valid_payload()
        payload["findings"][0]["category"] = "xss"
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_confidence_rejected(self):
        payload = _valid_payload()
        payload["findings"][0]["confidence"] = "absolute"
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_decision_rejected(self):
        resp = client.post("/ingest", json=_valid_payload(decision="reject"))
        assert resp.status_code == 422

    def test_risk_score_above_100_rejected(self):
        resp = client.post("/ingest", json=_valid_payload(risk_score=101))
        assert resp.status_code == 422

    def test_risk_score_below_zero_rejected(self):
        resp = client.post("/ingest", json=_valid_payload(risk_score=-1))
        assert resp.status_code == 422

    def test_missing_commit_sha_rejected(self):
        payload = _valid_payload()
        del payload["commit_sha"]
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_empty_body_rejected(self):
        resp = client.post("/ingest", json={})
        assert resp.status_code == 422

    def test_non_json_body_rejected(self):
        resp = client.post("/ingest", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Ingestion — round-trip compatibility
# ---------------------------------------------------------------------------

class TestIngestRoundTrip:
    def test_serialized_scan_result_accepted(self):
        """A ScanResult serialized to JSON should be accepted by /ingest."""
        sr = ScanResult(
            repo="acme/webapp",
            pr_number=10,
            commit_sha="abc1234",
            ref="main",
            decision=Decision.WARN,
            risk_score=35,
            findings=[],
        )
        payload = json.loads(sr.model_dump_json())
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 202

    def test_mock_run_output_accepted(self):
        """The JSON output of mock_run() should be ingestible."""
        output = mock_run()
        payload = json.loads(output["json"])
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["findings_count"] == len(output["result"].findings)
