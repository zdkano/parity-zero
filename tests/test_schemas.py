"""Tests for the parity-zero findings schema (core JSON contract).

These tests validate that:
  - Finding, ScanMeta, and ScanResult models enforce required fields
  - Enum values map to the findings taxonomy
  - Serialisation round-trips produce valid JSON
  - summary_counts works correctly
  - Invalid data is rejected
  - JSON shape is stable for ingestion use
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schemas.findings import (
    Category,
    Confidence,
    Decision,
    Finding,
    ScanMeta,
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

    def test_category_count_matches_mvp(self):
        assert len(Category) == 6


# ---------------------------------------------------------------------------
# Severity enum tests
# ---------------------------------------------------------------------------

class TestSeverity:
    def test_all_severity_values(self):
        assert {s.value for s in Severity} == {"high", "medium", "low"}

    def test_severity_is_string_enum(self):
        assert Severity.HIGH == "high"

    def test_severity_count(self):
        assert len(Severity) == 3


# ---------------------------------------------------------------------------
# Confidence enum tests
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_all_confidence_values(self):
        assert {c.value for c in Confidence} == {"high", "medium", "low"}

    def test_confidence_is_string_enum(self):
        assert Confidence.LOW == "low"

    def test_confidence_count(self):
        assert len(Confidence) == 3


# ---------------------------------------------------------------------------
# Decision enum tests
# ---------------------------------------------------------------------------

class TestDecision:
    def test_all_decision_values(self):
        assert {d.value for d in Decision} == {"block", "warn", "pass"}

    def test_decision_is_string_enum(self):
        assert Decision.BLOCK == "block"
        assert Decision.WARN == "warn"
        assert Decision.PASS == "pass"

    def test_decision_count(self):
        assert len(Decision) == 3


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

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValidationError):
            _make_finding(confidence="absolute")

    def test_start_line_must_be_positive(self):
        with pytest.raises(ValidationError):
            _make_finding(start_line=0)

    def test_finding_json_shape(self):
        """Finding JSON keys must match the expected contract shape."""
        f = _make_finding()
        data = f.model_dump()
        expected_keys = {
            "id",
            "category",
            "severity",
            "confidence",
            "title",
            "description",
            "file",
            "start_line",
            "end_line",
            "recommendation",
        }
        assert set(data.keys()) == expected_keys


# ---------------------------------------------------------------------------
# ScanMeta model tests
# ---------------------------------------------------------------------------

class TestScanMeta:
    def test_valid_scan_meta(self):
        meta = ScanMeta(
            repo="acme/webapp",
            pr_number=10,
            commit_sha="abc1234",
            ref="main",
        )
        assert meta.repo == "acme/webapp"
        assert meta.pr_number == 10

    def test_scan_meta_gets_auto_scan_id(self):
        meta = ScanMeta(
            repo="acme/webapp",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
        )
        assert meta.scan_id is not None
        assert len(meta.scan_id) == 32

    def test_scan_meta_gets_timestamp(self):
        meta = ScanMeta(
            repo="acme/webapp",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
        )
        assert isinstance(meta.timestamp, datetime)

    def test_scan_meta_repo_required(self):
        with pytest.raises(ValidationError):
            ScanMeta(pr_number=1, commit_sha="abc1234", ref="main")

    def test_scan_meta_ref_required(self):
        with pytest.raises(ValidationError):
            ScanMeta(repo="acme/webapp", pr_number=1, commit_sha="abc1234")

    def test_scan_meta_json_shape(self):
        meta = ScanMeta(
            repo="acme/webapp",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
        )
        expected_keys = {"scan_id", "repo", "pr_number", "commit_sha", "ref", "timestamp"}
        assert set(meta.model_dump().keys()) == expected_keys


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

    def test_decision_defaults_to_pass(self):
        sr = _make_scan_result()
        assert sr.decision == Decision.PASS

    def test_decision_can_be_set(self):
        sr = _make_scan_result(decision=Decision.BLOCK)
        assert sr.decision == Decision.BLOCK

    def test_invalid_decision_rejected(self):
        with pytest.raises(ValidationError):
            _make_scan_result(decision="reject")

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
        assert restored.decision == sr.decision
        assert len(restored.findings) == len(sr.findings)
        assert restored.findings[0].title == sr.findings[0].title

    def test_scan_result_json_shape(self):
        """ScanResult JSON keys must match the expected contract shape for ingestion."""
        sr = _make_scan_result()
        data = sr.model_dump()
        expected_keys = {
            "scan_id",
            "repo",
            "pr_number",
            "commit_sha",
            "ref",
            "timestamp",
            "decision",
            "findings",
        }
        assert set(data.keys()) == expected_keys

    def test_scan_result_inherits_scan_meta(self):
        assert issubclass(ScanResult, ScanMeta)

    def test_scan_result_decision_in_json_round_trip(self):
        sr = _make_scan_result(decision=Decision.WARN)
        json_str = sr.model_dump_json()
        restored = ScanResult.model_validate_json(json_str)
        assert restored.decision == Decision.WARN

    def test_ingestion_shape_stability(self):
        """Full payload shape check — validates the nested structure is stable
        for downstream ingestion consumers."""
        sr = _make_scan_result(decision=Decision.WARN)
        payload = sr.model_dump(mode="json")

        # Top-level keys
        assert "scan_id" in payload
        assert "repo" in payload
        assert "pr_number" in payload
        assert "commit_sha" in payload
        assert "ref" in payload
        assert "timestamp" in payload
        assert "decision" in payload
        assert "findings" in payload

        # Decision is serialised as its string value
        assert payload["decision"] == "warn"

        # Findings are serialised as dicts with expected keys
        assert len(payload["findings"]) == 1
        finding_keys = set(payload["findings"][0].keys())
        expected_finding_keys = {
            "id",
            "category",
            "severity",
            "confidence",
            "title",
            "description",
            "file",
            "start_line",
            "end_line",
            "recommendation",
        }
        assert finding_keys == expected_finding_keys
