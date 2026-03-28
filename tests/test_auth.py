"""Tests for backend authentication (bearer token auth).

Validates:
  - Requests without auth are rejected (401)
  - Requests with wrong token are rejected (401)
  - Requests with valid token succeed
  - Auth is enforced on ingest endpoint
  - Auth is enforced on retrieval endpoints
  - Health endpoint does not require auth
  - Server rejects requests when PARITY_ZERO_AUTH_TOKEN is not configured
"""

import os

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.persistence import ScanStore
from api.routes.ingest import _get_store as ingest_get_store
from api.routes.runs import _get_store as runs_get_store
from schemas.findings import Category, Confidence, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_TOKEN = "secret-test-token-12345"


def _valid_payload(**overrides) -> dict:
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
                "title": "Test finding",
                "description": "Test description.",
                "file": "src/app.py",
                "start_line": 1,
            }
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Auth-aware client — does NOT override auth dependency
# ---------------------------------------------------------------------------

class TestAuthEnforcement:
    """Tests with real auth enforcement (no dependency override)."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        """Set up a fresh app with real auth and in-memory store."""
        # Remove any dependency overrides from other test modules
        from api.auth import require_auth
        app.dependency_overrides.pop(require_auth, None)

        # Set up in-memory store
        self._store = ScanStore(":memory:")
        app.dependency_overrides[ingest_get_store] = lambda: self._store
        app.dependency_overrides[runs_get_store] = lambda: self._store

        # Set the expected auth token
        monkeypatch.setenv("PARITY_ZERO_AUTH_TOKEN", _VALID_TOKEN)

        self._client = TestClient(app)
        yield

        # Clean up
        app.dependency_overrides.pop(ingest_get_store, None)
        app.dependency_overrides.pop(runs_get_store, None)

    def test_health_no_auth_required(self):
        resp = self._client.get("/health")
        assert resp.status_code == 200

    def test_ingest_without_auth_rejected(self):
        resp = self._client.post("/ingest", json=_valid_payload())
        assert resp.status_code == 401

    def test_ingest_with_wrong_token_rejected(self):
        resp = self._client.post(
            "/ingest",
            json=_valid_payload(),
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_ingest_with_valid_token_accepted(self):
        resp = self._client.post(
            "/ingest",
            json=_valid_payload(),
            headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
        )
        assert resp.status_code == 202

    def test_list_runs_without_auth_rejected(self):
        resp = self._client.get("/runs")
        assert resp.status_code == 401

    def test_list_runs_with_valid_token(self):
        resp = self._client.get(
            "/runs",
            headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_get_run_without_auth_rejected(self):
        resp = self._client.get("/runs/some-id")
        assert resp.status_code == 401

    def test_get_run_with_valid_token(self):
        resp = self._client.get(
            "/runs/nonexistent",
            headers={"Authorization": f"Bearer {_VALID_TOKEN}"},
        )
        # 404 because run doesn't exist — but auth passed
        assert resp.status_code == 404

    def test_malformed_auth_header_rejected(self):
        resp = self._client.post(
            "/ingest",
            json=_valid_payload(),
            headers={"Authorization": "NotBearer token"},
        )
        assert resp.status_code in (401, 403)


class TestAuthTokenNotConfigured:
    """Tests when PARITY_ZERO_AUTH_TOKEN is not set on the server."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        from api.auth import require_auth
        app.dependency_overrides.pop(require_auth, None)

        self._store = ScanStore(":memory:")
        app.dependency_overrides[ingest_get_store] = lambda: self._store
        app.dependency_overrides[runs_get_store] = lambda: self._store

        monkeypatch.delenv("PARITY_ZERO_AUTH_TOKEN", raising=False)

        self._client = TestClient(app)
        yield

        app.dependency_overrides.pop(ingest_get_store, None)
        app.dependency_overrides.pop(runs_get_store, None)

    def test_ingest_rejected_when_no_server_token(self):
        """Even with a bearer token in request, server rejects if not configured."""
        resp = self._client.post(
            "/ingest",
            json=_valid_payload(),
            headers={"Authorization": "Bearer some-token"},
        )
        assert resp.status_code == 401
        assert "not configured" in resp.json()["detail"]
