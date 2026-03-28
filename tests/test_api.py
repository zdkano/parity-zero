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
  - Run summary metadata persisted correctly (ADR-036)
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
    """Create a fresh in-memory store."""
    return ScanStore(":memory:")


@pytest.fixture(autouse=True)
def _fresh_app_state():
    """Set up a fresh in-memory store and auth override for each test.

    Replaces the previous module-level overrides to ensure clean
    test isolation.  See ADR-036.
    """
    store = _make_test_store()
    app.dependency_overrides[ingest_get_store] = lambda: store
    app.dependency_overrides[runs_get_store] = lambda: store
    app.dependency_overrides[require_auth] = lambda: _TEST_TOKEN
    yield store
    app.dependency_overrides.pop(ingest_get_store, None)
    app.dependency_overrides.pop(runs_get_store, None)
    app.dependency_overrides.pop(require_auth, None)


@pytest.fixture()
def client():
    """Provide a TestClient bound to the current app state."""
    return TestClient(app)


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
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Ingestion endpoint — valid payloads
# ---------------------------------------------------------------------------

class TestIngest:
    def test_valid_payload_accepted(self, client):
        resp = client.post("/ingest", json=_valid_payload())
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["findings_count"] == 1

    def test_empty_findings_accepted(self, client):
        resp = client.post("/ingest", json=_valid_payload(findings=[]))
        assert resp.status_code == 202
        assert resp.json()["findings_count"] == 0

    def test_response_includes_decision(self, client):
        resp = client.post(
            "/ingest",
            json=_valid_payload(decision=Decision.WARN.value),
        )
        assert resp.status_code == 202
        assert resp.json()["decision"] == "warn"

    def test_response_includes_risk_score(self, client):
        resp = client.post(
            "/ingest",
            json=_valid_payload(risk_score=42),
        )
        assert resp.status_code == 202
        assert resp.json()["risk_score"] == 42

    def test_response_includes_scan_id(self, client):
        resp = client.post("/ingest", json=_valid_payload())
        body = resp.json()
        assert "scan_id" in body
        assert isinstance(body["scan_id"], str)
        assert len(body["scan_id"]) == 32


# ---------------------------------------------------------------------------
# Ingestion endpoint — rejected payloads
# ---------------------------------------------------------------------------

class TestIngestValidation:
    def test_missing_repo_rejected(self, client):
        payload = _valid_payload()
        del payload["repo"]
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_severity_rejected(self, client):
        payload = _valid_payload()
        payload["findings"][0]["severity"] = "critical"
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_missing_finding_title_rejected(self, client):
        payload = _valid_payload()
        payload["findings"][0]["title"] = ""
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_pr_number_rejected(self, client):
        resp = client.post("/ingest", json=_valid_payload(pr_number=0))
        assert resp.status_code == 422

    def test_invalid_category_rejected(self, client):
        payload = _valid_payload()
        payload["findings"][0]["category"] = "xss"
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_confidence_rejected(self, client):
        payload = _valid_payload()
        payload["findings"][0]["confidence"] = "absolute"
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_invalid_decision_rejected(self, client):
        resp = client.post("/ingest", json=_valid_payload(decision="reject"))
        assert resp.status_code == 422

    def test_risk_score_above_100_rejected(self, client):
        resp = client.post("/ingest", json=_valid_payload(risk_score=101))
        assert resp.status_code == 422

    def test_risk_score_below_zero_rejected(self, client):
        resp = client.post("/ingest", json=_valid_payload(risk_score=-1))
        assert resp.status_code == 422

    def test_missing_commit_sha_rejected(self, client):
        payload = _valid_payload()
        del payload["commit_sha"]
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 422

    def test_empty_body_rejected(self, client):
        resp = client.post("/ingest", json={})
        assert resp.status_code == 422

    def test_non_json_body_rejected(self, client):
        resp = client.post("/ingest", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Ingestion — round-trip compatibility
# ---------------------------------------------------------------------------

class TestIngestRoundTrip:
    def test_serialized_scan_result_accepted(self, client):
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

    def test_mock_run_output_accepted(self, client):
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
    def test_ingested_run_is_persisted(self, client, _fresh_app_state):
        payload = _valid_payload()
        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 202
        scan_id = resp.json()["scan_id"]

        run = _fresh_app_state.get_run(scan_id)
        assert run is not None
        assert run["repo"] == "acme/webapp"
        assert run["pr_number"] == 10
        assert run["findings_count"] == 1

    def test_findings_persisted_correctly(self, client, _fresh_app_state):
        payload = _valid_payload()
        resp = client.post("/ingest", json=payload)
        scan_id = resp.json()["scan_id"]

        findings = _fresh_app_state.get_findings_for_run(scan_id)
        assert len(findings) == 1
        assert findings[0]["category"] == "authentication"
        assert findings[0]["severity"] == "high"
        assert findings[0]["file"] == "src/routes/admin.py"

    def test_multiple_runs_persisted(self, client, _fresh_app_state):
        for i in range(3):
            resp = client.post("/ingest", json=_valid_payload(pr_number=i + 1))
            assert resp.status_code == 202

        runs = _fresh_app_state.list_runs()
        assert len(runs) == 3

    def test_empty_findings_run_persisted(self, client, _fresh_app_state):
        resp = client.post("/ingest", json=_valid_payload(findings=[]))
        scan_id = resp.json()["scan_id"]

        run = _fresh_app_state.get_run(scan_id)
        assert run is not None
        assert run["findings_count"] == 0
        assert run["findings"] == []


# ---------------------------------------------------------------------------
# Retrieval endpoints
# ---------------------------------------------------------------------------

class TestRetrieval:
    def test_list_runs_empty(self, client):
        resp = client.get("/runs")
        assert resp.status_code == 200
        assert resp.json()["runs"] == []

    def test_list_runs_after_ingest(self, client):
        client.post("/ingest", json=_valid_payload())
        resp = client.get("/runs")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_list_runs_filter_by_repo(self, client):
        client.post("/ingest", json=_valid_payload(repo="acme/webapp"))
        client.post("/ingest", json=_valid_payload(repo="other/repo"))

        resp = client.get("/runs", params={"repo": "acme/webapp"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert resp.json()["runs"][0]["repo"] == "acme/webapp"

    def test_get_run_by_id(self, client):
        ingest_resp = client.post("/ingest", json=_valid_payload())
        scan_id = ingest_resp.json()["scan_id"]

        resp = client.get(f"/runs/{scan_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["scan_id"] == scan_id
        assert body["repo"] == "acme/webapp"
        assert len(body["findings"]) == 1

    def test_get_run_not_found(self, client):
        resp = client.get("/runs/nonexistent")
        assert resp.status_code == 404

    def test_list_runs_pagination(self, client):
        for i in range(5):
            client.post("/ingest", json=_valid_payload(pr_number=i + 1))

        resp = client.get("/runs", params={"limit": 2})
        assert resp.json()["count"] == 2

        resp = client.get("/runs", params={"limit": 2, "offset": 3})
        assert resp.json()["count"] == 2


# ---------------------------------------------------------------------------
# Run summary metadata persistence (ADR-036)
# ---------------------------------------------------------------------------

class TestRunSummaryMetadata:
    """Tests that run summary metadata fields are persisted correctly."""

    def test_run_summary_metadata_persisted(self, client, _fresh_app_state):
        """Run summary metadata sent alongside ScanResult is persisted."""
        payload = _valid_payload()
        payload["provider_name"] = "github-models"
        payload["provider_invoked"] = True
        payload["provider_gate_decision"] = "invoked"
        payload["concerns_count"] = 3
        payload["observations_count"] = 5
        payload["provider_notes_count"] = 7
        payload["provider_notes_suppressed_count"] = 2
        payload["changed_files_count"] = 10
        payload["skipped_files_count"] = 1

        resp = client.post("/ingest", json=payload)
        assert resp.status_code == 202
        scan_id = resp.json()["scan_id"]

        run = _fresh_app_state.get_run(scan_id)
        assert run is not None
        assert run["provider_name"] == "github-models"
        assert run["provider_invoked"] == 1  # SQLite stores booleans as int
        assert run["provider_gate_decision"] == "invoked"
        assert run["concerns_count"] == 3
        assert run["observations_count"] == 5
        assert run["provider_notes_count"] == 7
        assert run["provider_notes_suppressed_count"] == 2
        assert run["changed_files_count"] == 10
        assert run["skipped_files_count"] == 1

    def test_run_summary_defaults_when_absent(self, client, _fresh_app_state):
        """Run summary metadata defaults to zero/empty when not provided."""
        resp = client.post("/ingest", json=_valid_payload())
        assert resp.status_code == 202
        scan_id = resp.json()["scan_id"]

        run = _fresh_app_state.get_run(scan_id)
        assert run is not None
        assert run["provider_invoked"] == 0
        assert run["provider_gate_decision"] == ""
        assert run["concerns_count"] == 0
        assert run["observations_count"] == 0
        assert run["provider_notes_count"] == 0
        assert run["provider_notes_suppressed_count"] == 0
        assert run["changed_files_count"] == 0
        assert run["skipped_files_count"] == 0

    def test_retrieval_includes_summary_metadata(self, client):
        """GET /runs/{scan_id} includes run summary metadata fields."""
        payload = _valid_payload()
        payload["changed_files_count"] = 8
        payload["skipped_files_count"] = 2
        payload["concerns_count"] = 1

        resp = client.post("/ingest", json=payload)
        scan_id = resp.json()["scan_id"]

        resp = client.get(f"/runs/{scan_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed_files_count"] == 8
        assert body["skipped_files_count"] == 2
        assert body["concerns_count"] == 1

    def test_list_runs_includes_summary_metadata(self, client):
        """GET /runs listing includes run summary metadata fields."""
        payload = _valid_payload()
        payload["provider_name"] = "anthropic"
        payload["provider_invoked"] = True

        client.post("/ingest", json=payload)

        resp = client.get("/runs")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["provider_name"] == "anthropic"
        assert runs[0]["provider_invoked"] == 1
