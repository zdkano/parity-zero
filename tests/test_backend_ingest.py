"""Tests for action-to-backend ingest wiring.

Validates:
  - _send_to_backend skips when PARITY_ZERO_API_URL is not set
  - _send_to_backend skips when PARITY_ZERO_API_TOKEN is not set
  - _send_to_backend attempts POST when both are set
  - _send_to_backend sends correct auth header
  - _send_to_backend handles HTTP errors gracefully
  - _send_to_backend handles network errors gracefully
  - _send_to_backend does not crash the action on failure
"""

import json
import os
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from schemas.findings import Decision, ScanResult
from reviewer.action import _send_to_backend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scan_result(**overrides) -> ScanResult:
    defaults = {
        "repo": "acme/webapp",
        "pr_number": 42,
        "commit_sha": "abc1234",
        "ref": "feature/test",
        "decision": Decision.PASS,
        "risk_score": 0,
        "findings": [],
    }
    defaults.update(overrides)
    return ScanResult(**defaults)


# ---------------------------------------------------------------------------
# Skip behavior
# ---------------------------------------------------------------------------

class TestBackendIngestSkip:
    def test_skips_when_no_api_url(self, monkeypatch):
        monkeypatch.delenv("PARITY_ZERO_API_URL", raising=False)
        monkeypatch.delenv("PARITY_ZERO_API_TOKEN", raising=False)
        result = _send_to_backend(_make_scan_result())
        assert result is False

    def test_skips_when_api_url_empty(self, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token123")
        result = _send_to_backend(_make_scan_result())
        assert result is False

    def test_skips_when_no_api_token(self, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.delenv("PARITY_ZERO_API_TOKEN", raising=False)
        result = _send_to_backend(_make_scan_result())
        assert result is False

    def test_skips_when_api_token_empty(self, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "")
        result = _send_to_backend(_make_scan_result())
        assert result is False


# ---------------------------------------------------------------------------
# Attempt behavior
# ---------------------------------------------------------------------------

class TestBackendIngestAttempt:
    @patch("reviewer.action.urllib.request.urlopen")
    def test_sends_post_with_auth_header(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "secret-token")

        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 202
        mock_resp.read.return_value = b'{"status": "accepted"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        sr = _make_scan_result()
        result = _send_to_backend(sr)
        assert result is True

        # Verify the request was made correctly
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "http://localhost:8000/ingest"
        assert req.get_header("Authorization") == "Bearer secret-token"
        assert req.get_header("Content-type") == "application/json"

    @patch("reviewer.action.urllib.request.urlopen")
    def test_sends_scan_result_as_json_body(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 202
        mock_resp.read.return_value = b'{"status": "accepted"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        sr = _make_scan_result()
        _send_to_backend(sr)

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data.decode("utf-8"))
        assert body["repo"] == "acme/webapp"
        assert body["pr_number"] == 42
        assert "scan_id" in body

    @patch("reviewer.action.urllib.request.urlopen")
    def test_strips_trailing_slash_from_url(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000/")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 202
        mock_resp.read.return_value = b'{"status": "accepted"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        _send_to_backend(_make_scan_result())

        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "http://localhost:8000/ingest"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestBackendIngestErrors:
    @patch("reviewer.action.urllib.request.urlopen")
    def test_handles_http_error_gracefully(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://localhost:8000/ingest", 401, "Unauthorized", {}, None
        )

        result = _send_to_backend(_make_scan_result())
        assert result is False  # does not raise

    @patch("reviewer.action.urllib.request.urlopen")
    def test_handles_network_error_gracefully(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = _send_to_backend(_make_scan_result())
        assert result is False  # does not raise

    @patch("reviewer.action.urllib.request.urlopen")
    def test_handles_timeout_gracefully(self, mock_urlopen, monkeypatch):
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        mock_urlopen.side_effect = OSError("Connection timed out")

        result = _send_to_backend(_make_scan_result())
        assert result is False  # does not raise
