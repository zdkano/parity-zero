"""Hardening and storage-shape evolution tests (ADR-036).

Validates:
  - Skipped-file metadata preservation
  - SkippedFile model correctness
  - PRContent carries skipped files
  - Backend ingest remains non-fatal when failing
  - ScanResult JSON contract remains unchanged
  - Scoring is unchanged
  - Provider trust boundaries unchanged
  - No internal structures leak into public contract or API
  - Run summary metadata fields round-trip correctly
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

from reviewer.models import PRContent, PRFile, SkippedFile, ReviewTrace
from schemas.findings import (
    Category,
    Confidence,
    Decision,
    Finding,
    ScanResult,
    Severity,
)
from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk


# =====================================================================
# SkippedFile model
# =====================================================================


class TestSkippedFileModel:
    """Tests for the SkippedFile dataclass."""

    def test_create_not_found(self):
        sf = SkippedFile(path="deleted.py", reason="not_found")
        assert sf.path == "deleted.py"
        assert sf.reason == "not_found"

    def test_create_binary(self):
        sf = SkippedFile(path="image.png", reason="binary")
        assert sf.path == "image.png"
        assert sf.reason == "binary"

    def test_create_too_large(self):
        sf = SkippedFile(path="huge.sql", reason="too_large")
        assert sf.reason == "too_large"

    def test_create_unreadable(self):
        sf = SkippedFile(path="secret.key", reason="unreadable")
        assert sf.reason == "unreadable"

    def test_frozen(self):
        sf = SkippedFile(path="file.py", reason="binary")
        with pytest.raises(AttributeError):
            sf.path = "other.py"


# =====================================================================
# PRContent with skipped files
# =====================================================================


class TestPRContentSkippedFiles:
    """Tests that PRContent correctly carries skipped-file metadata."""

    def test_from_dict_without_skipped(self):
        pr = PRContent.from_dict({"a.py": "pass\n"})
        assert pr.file_count == 1
        assert pr.skipped_file_count == 0
        assert pr.skipped_files == []

    def test_from_dict_with_skipped(self):
        skipped = [
            SkippedFile(path="deleted.py", reason="not_found"),
            SkippedFile(path="big.bin", reason="too_large"),
        ]
        pr = PRContent.from_dict({"a.py": "pass\n"}, skipped=skipped)
        assert pr.file_count == 1
        assert pr.skipped_file_count == 2
        assert pr.skipped_files[0].path == "deleted.py"
        assert pr.skipped_files[1].path == "big.bin"

    def test_empty_with_all_skipped(self):
        skipped = [SkippedFile(path="binary.dat", reason="binary")]
        pr = PRContent.from_dict({}, skipped=skipped)
        assert pr.file_count == 0
        assert pr.skipped_file_count == 1

    def test_skipped_files_do_not_appear_in_to_dict(self):
        skipped = [SkippedFile(path="big.bin", reason="too_large")]
        pr = PRContent.from_dict({"a.py": "pass\n"}, skipped=skipped)
        d = pr.to_dict()
        assert "big.bin" not in d
        assert "a.py" in d


# =====================================================================
# Backend ingest non-fatal behavior
# =====================================================================


class TestBackendIngestNonFatal:
    """Tests that backend ingest failure does not crash the reviewer action."""

    def test_send_to_backend_skips_when_no_url(self, monkeypatch):
        from reviewer.action import _send_to_backend

        monkeypatch.delenv("PARITY_ZERO_API_URL", raising=False)
        monkeypatch.delenv("PARITY_ZERO_API_TOKEN", raising=False)

        result = ScanResult(
            repo="test/repo", pr_number=1, commit_sha="abc1234",
            ref="main", findings=[],
        )
        assert _send_to_backend(result) is False

    def test_send_to_backend_skips_when_no_token(self, monkeypatch):
        from reviewer.action import _send_to_backend

        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.delenv("PARITY_ZERO_API_TOKEN", raising=False)

        result = ScanResult(
            repo="test/repo", pr_number=1, commit_sha="abc1234",
            ref="main", findings=[],
        )
        assert _send_to_backend(result) is False

    @mock.patch("reviewer.action.urllib.request.urlopen")
    def test_send_to_backend_handles_http_error(self, mock_urlopen, monkeypatch):
        import urllib.error
        from reviewer.action import _send_to_backend

        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://localhost:8000/ingest", 500, "Internal Server Error", {}, None
        )

        result = ScanResult(
            repo="test/repo", pr_number=1, commit_sha="abc1234",
            ref="main", findings=[],
        )
        # Must not raise — returns False
        assert _send_to_backend(result) is False

    @mock.patch("reviewer.action.urllib.request.urlopen")
    def test_send_to_backend_handles_network_error(self, mock_urlopen, monkeypatch):
        import urllib.error
        from reviewer.action import _send_to_backend

        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = ScanResult(
            repo="test/repo", pr_number=1, commit_sha="abc1234",
            ref="main", findings=[],
        )
        assert _send_to_backend(result) is False

    @mock.patch("reviewer.action.urllib.request.urlopen")
    def test_send_to_backend_includes_summary_metadata(self, mock_urlopen, monkeypatch):
        """When analysis is provided, summary metadata is included in payload."""
        monkeypatch.setenv("PARITY_ZERO_API_URL", "http://localhost:8000")
        monkeypatch.setenv("PARITY_ZERO_API_TOKEN", "token")

        # Mock successful response
        mock_resp = mock.MagicMock()
        mock_resp.getcode.return_value = 202
        mock_resp.read.return_value = b'{"status":"accepted"}'
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = ScanResult(
            repo="test/repo", pr_number=1, commit_sha="abc1234",
            ref="main", findings=[],
        )

        trace = ReviewTrace(
            provider_attempted=True,
            provider_gate_decision="invoked",
            provider_name="github-models",
            provider_notes_returned=5,
            provider_notes_suppressed=2,
        )
        analysis = AnalysisResult(trace=trace, concerns=["c1", "c2"], observations=["o1"])

        from reviewer.action import _send_to_backend
        sent = _send_to_backend(
            result, analysis=analysis,
            changed_files_count=10, skipped_files_count=3,
        )
        assert sent is True

        # Verify the payload contains summary metadata
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        payload = json.loads(request_obj.data.decode("utf-8"))
        assert payload["provider_invoked"] is True
        assert payload["provider_gate_decision"] == "invoked"
        assert payload["provider_name"] == "github-models"
        assert payload["concerns_count"] == 2
        assert payload["observations_count"] == 1
        assert payload["provider_notes_count"] == 5
        assert payload["provider_notes_suppressed_count"] == 2
        assert payload["changed_files_count"] == 10
        assert payload["skipped_files_count"] == 3


# =====================================================================
# ScanResult contract unchanged
# =====================================================================


class TestScanResultContractUnchanged:
    """Tests that the ScanResult JSON contract has not changed."""

    def test_required_fields_present(self):
        sr = ScanResult(
            repo="acme/webapp", pr_number=1, commit_sha="abc1234",
            ref="main", findings=[],
        )
        data = json.loads(sr.model_dump_json())
        for key in ("scan_id", "repo", "pr_number", "commit_sha", "ref",
                     "timestamp", "decision", "risk_score", "findings"):
            assert key in data, f"Missing required field: {key}"

    def test_no_internal_fields_in_json(self):
        sr = ScanResult(
            repo="acme/webapp", pr_number=1, commit_sha="abc1234",
            ref="main", findings=[],
        )
        data = json.loads(sr.model_dump_json())
        internal_fields = (
            "trace", "concerns", "observations", "provider_notes",
            "bundle", "reasoning_notes", "skipped_files",
            "provider_invoked", "provider_gate_decision",
            "concerns_count", "observations_count",
        )
        for field in internal_fields:
            assert field not in data, f"Internal field leaked: {field}"

    def test_finding_fields_complete(self):
        f = Finding(
            category=Category.SECRETS, severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            title="AWS key", description="Found key", file="deploy.py",
        )
        data = f.model_dump(mode="json")
        for key in ("id", "category", "severity", "confidence",
                     "title", "description", "file"):
            assert key in data

    def test_json_round_trip(self):
        sr = ScanResult(
            repo="acme/webapp", pr_number=1, commit_sha="abc1234",
            ref="main", decision=Decision.WARN, risk_score=25,
            findings=[
                Finding(
                    category=Category.SECRETS, severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    title="Key found", description="AWS key", file="x.py",
                ),
            ],
        )
        json_str = sr.model_dump_json()
        restored = ScanResult.model_validate_json(json_str)
        assert restored.scan_id == sr.scan_id
        assert len(restored.findings) == 1


# =====================================================================
# Scoring unchanged
# =====================================================================


class TestScoringUnchanged:
    """Tests that scoring derivation has not changed."""

    def test_no_findings_is_pass(self):
        decision, risk = derive_decision_and_risk([])
        assert decision == Decision.PASS
        assert risk == 0

    def test_single_high_severity_is_warn(self):
        findings = [
            Finding(
                category=Category.SECRETS, severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                title="Key", description="Found key", file="x.py",
            ),
        ]
        decision, risk = derive_decision_and_risk(findings)
        assert decision == Decision.WARN
        assert risk == 25

    def test_low_severity_is_pass(self):
        findings = [
            Finding(
                category=Category.INSECURE_CONFIGURATION,
                severity=Severity.LOW, confidence=Confidence.MEDIUM,
                title="Minor", description="Minor issue", file="x.py",
            ),
        ]
        decision, risk = derive_decision_and_risk(findings)
        assert decision == Decision.PASS
        assert risk == 5


# =====================================================================
# Provider trust boundaries unchanged
# =====================================================================


class TestProviderTrustBoundaries:
    """Tests that provider output does not influence scoring or findings."""

    def test_analysis_result_trace_not_in_scan_result(self):
        """ReviewTrace data does not appear in ScanResult JSON."""
        analysis = analyse({"clean.py": "print('hello')\n"})
        sr = ScanResult(
            repo="test/repo", pr_number=1, commit_sha="abc1234",
            ref="main",
            decision=Decision.PASS, risk_score=0,
            findings=analysis.findings,
        )
        data = json.loads(sr.model_dump_json())
        assert "trace" not in data
        assert "provider_gate_decision" not in data
        assert "provider_notes" not in data
        assert "concerns" not in data
        assert "observations" not in data

    def test_scoring_independent_of_trace(self):
        """Scoring is derived solely from findings, not trace."""
        f = Finding(
            category=Category.SECRETS, severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            title="Key", description="Found key", file="x.py",
        )
        decision, risk = derive_decision_and_risk([f])
        assert decision == Decision.WARN
        assert risk == 25
        # Same findings, same score — trace does not affect it
