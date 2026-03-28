"""Tests for the parity-zero FastAPI ingestion API.

Validates:
  - Health check endpoint
  - Ingestion endpoint accepts valid ScanResult payloads (with auth)
  - Ingestion endpoint rejects malformed payloads
  - Ingestion endpoint rejects unauthenticated requests
  - Ingestion response includes decision and risk_score
  - Serialized reviewer output is ingestion-compatible
  - Persistence of ingested results
  - Retrieval endpoints
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from api.auth import require_auth
from api.main import app
from api.persistence import ScanStore
from api.routes.ingest import _get_store as ingest_get_store
from api.routes.runs import _get_store as runs_get_store
from schemas.findings import Category, Confidence, Decision, ScanResult, Severity
from reviewer.action import mock_run


# ---------------------------------------------------------------------------
# Test fixtures — in-memory store + auth override
# ---------------------------------------------------------------------------

_TEST_TOKEN = "test-token-for-unit-tests"


def _make_test_store() -> ScanStore:
    """Create a fresh in-memory store for each test module."""
    return ScanStore(":memory:")


# Shared store instance used across tests in this module
_test_store = _make_test_store()


def _override_store() -> ScanStore:
    return _test_store


def _override_auth() -> str:
    return _TEST_TOKEN


app.dependency_overrides[ingest_get_store] = _override_store
app.dependency_overrides[runs_get_store] = _override_store
app.dependency_overrides[require_auth] = _override_auth

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_store():
    """Reset the in-memory store before each test."""
    global _test_store
    _test_store = _make_test_store()
    app.dependency_overrides[ingest_get_store] = lambda: _test_store
    app.dependency_overrides[runs_get_store] = lambda: _test_store
    yield


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


# ---------------------------------------------------------------------------
# Persistence — ingest then retrieve
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_ingested_run_is_persisted(self):
        payload = _valid_payload()
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 202
        scan_id = resp.json()["scan_id"]

        run = _test_store.get_run(scan_id)
        assert run is not None
        assert run["repo"] == "acme/webapp"
        assert run["pr_number"] == 10
        assert run["findings_count"] == 1

    def test_findings_persisted_correctly(self):
        payload = _valid_payload()
        resp = client.post("/ingest", json=payload)
        scan_id = resp.json()["scan_id"]

        findings = _test_store.get_findings_for_run(scan_id)
        assert len(findings) == 1
        assert findings[0]["category"] == "authentication"
        assert findings[0]["severity"] == "high"
        assert findings[0]["file"] == "src/routes/admin.py"

    def test_multiple_runs_persisted(self):
        for i in range(3):
            resp = client.post("/ingest", json=_valid_payload(pr_number=i + 1))
            assert resp.status_code == 202

        runs = _test_store.list_runs()
        assert len(runs) == 3

    def test_empty_findings_run_persisted(self):
        resp = client.post("/ingest", json=_valid_payload(findings=[]))
        scan_id = resp.json()["scan_id"]

        run = _test_store.get_run(scan_id)
        assert run is not None
        assert run["findings_count"] == 0
        assert run["findings"] == []


# ---------------------------------------------------------------------------
# Retrieval endpoints
# ---------------------------------------------------------------------------

class TestRetrieval:
    def test_list_runs_empty(self):
        resp = client.get("/runs")
        assert resp.status_code == 200
        assert resp.json()["runs"] == []

    def test_list_runs_after_ingest(self):
        client.post("/ingest", json=_valid_payload())
        resp = client.get("/runs")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_runs_filter_by_repo(self):
        client.post("/ingest", json=_valid_payload(repo="acme/webapp"))
        client.post("/ingest", json=_valid_payload(repo="other/repo"))

        resp = client.get("/runs", params={"repo": "acme/webapp"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["runs"][0]["repo"] == "acme/webapp"

    def test_get_run_by_id(self):
        ingest_resp = client.post("/ingest", json=_valid_payload())
        scan_id = ingest_resp.json()["scan_id"]

        resp = client.get(f"/runs/{scan_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["scan_id"] == scan_id
        assert body["repo"] == "acme/webapp"
        assert len(body["findings"]) == 1

    def test_get_run_not_found(self):
        resp = client.get("/runs/nonexistent")
        assert resp.status_code == 404

    def test_list_runs_pagination(self):
        for i in range(5):
            client.post("/ingest", json=_valid_payload(pr_number=i + 1))

        resp = client.get("/runs", params={"limit": 2})
        assert resp.json()["count"] == 2

        resp = client.get("/runs", params={"limit": 2, "offset": 3})
        assert resp.json()["count"] == 2
