"""Tests for the parity-zero findings schema (core JSON contract).

These tests validate that:
  - Finding and ScanResult models enforce required fields
  - Enum values map to the findings taxonomy
  - Serialisation round-trips produce valid JSON
  - summary_counts works correctly
  - Invalid data is rejected
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schemas.findings import (
    Category,
    Confidence,
    Finding,
    ScanResult,
    Severity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(**overrides) -> Finding:
    """Create a valid Finding with sensible defaults, overridden as needed."""
    defaults = {
        "category": Category.AUTHENTICATION,
        "severity": Severity.HIGH,
        "confidence": Confidence.MEDIUM,
        "title": "Missing auth check",
        "description": "The /admin route has no authentication middleware.",
        "file": "src/routes/admin.py",
        "start_line": 42,
        "end_line": 42,
        "recommendation": "Add authentication middleware to this route.",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_scan_result(**overrides) -> ScanResult:
    """Create a valid ScanResult with sensible defaults."""
    defaults = {
        "repo": "acme/webapp",
        "pr_number": 123,
        "commit_sha": "abc1234",
        "ref": "feature/login",
        "findings": [_make_finding()],
    }
    defaults.update(overrides)
    return ScanResult(**defaults)


# ---------------------------------------------------------------------------
# Category enum tests
# ---------------------------------------------------------------------------

class TestCategory:
    def test_all_taxonomy_categories_present(self):
        expected = {
            "authentication",
            "authorization",
            "input_validation",
            "secrets",
            "insecure_configuration",
            "dependency_risk",
        }
        assert {c.value for c in Category} == expected

    def test_category_is_string_enum(self):
        assert Category.SECRETS == "secrets"


# ---------------------------------------------------------------------------
# Finding model tests
# ---------------------------------------------------------------------------

class TestFinding:
    def test_valid_finding_creates_successfully(self):
        f = _make_finding()
        assert f.category == Category.AUTHENTICATION
        assert f.severity == Severity.HIGH
        assert f.confidence == Confidence.MEDIUM
        assert f.file == "src/routes/admin.py"

    def test_finding_gets_auto_id(self):
        f = _make_finding()
        assert f.id is not None
        assert len(f.id) == 12

    def test_finding_title_required(self):
        with pytest.raises(ValidationError):
            _make_finding(title="")

    def test_finding_description_required(self):
        with pytest.raises(ValidationError):
            _make_finding(description="")

    def test_finding_file_required(self):
        with pytest.raises(ValidationError):
            Finding(
                category=Category.SECRETS,
                severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                title="Hardcoded API key",
                description="An API key is hardcoded.",
                # file is missing
            )

    def test_optional_fields_can_be_none(self):
        f = _make_finding(start_line=None, end_line=None, recommendation=None)
        assert f.start_line is None
        assert f.end_line is None
        assert f.recommendation is None

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            _make_finding(severity="critical")

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            _make_finding(category="xss")

    def test_start_line_must_be_positive(self):
        with pytest.raises(ValidationError):
            _make_finding(start_line=0)


# ---------------------------------------------------------------------------
# ScanResult model tests
# ---------------------------------------------------------------------------

class TestScanResult:
    def test_valid_scan_result(self):
        sr = _make_scan_result()
        assert sr.repo == "acme/webapp"
        assert sr.pr_number == 123
        assert len(sr.findings) == 1

    def test_scan_result_gets_auto_scan_id(self):
        sr = _make_scan_result()
        assert sr.scan_id is not None
        assert len(sr.scan_id) == 32

    def test_scan_result_gets_timestamp(self):
        sr = _make_scan_result()
        assert isinstance(sr.timestamp, datetime)

    def test_empty_findings_allowed(self):
        sr = _make_scan_result(findings=[])
        assert sr.findings == []

    def test_pr_number_must_be_positive(self):
        with pytest.raises(ValidationError):
            _make_scan_result(pr_number=0)

    def test_commit_sha_minimum_length(self):
        with pytest.raises(ValidationError):
            _make_scan_result(commit_sha="abc")

    def test_summary_counts(self):
        findings = [
            _make_finding(severity=Severity.HIGH),
            _make_finding(severity=Severity.HIGH),
            _make_finding(severity=Severity.MEDIUM),
            _make_finding(severity=Severity.LOW),
        ]
        sr = _make_scan_result(findings=findings)
        assert sr.summary_counts == {"high": 2, "medium": 1, "low": 1}

    def test_summary_counts_empty(self):
        sr = _make_scan_result(findings=[])
        assert sr.summary_counts == {"high": 0, "medium": 0, "low": 0}

    def test_json_round_trip(self):
        sr = _make_scan_result()
        json_str = sr.model_dump_json()
        restored = ScanResult.model_validate_json(json_str)
        assert restored.scan_id == sr.scan_id
        assert len(restored.findings) == len(sr.findings)
        assert restored.findings[0].title == sr.findings[0].title
