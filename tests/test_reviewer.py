"""Tests for the parity-zero reviewer components.

Phase 1: smoke tests validating the engine wiring, formatter output, and
the orchestration flow.  Detection-specific tests will be added alongside
real check implementations.
"""

import pytest

from schemas.findings import (
    Category,
    Confidence,
    Finding,
    ScanResult,
    Severity,
)
from reviewer.engine import analyse, _deduplicate
from reviewer.formatter import format_markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(**overrides) -> Finding:
    defaults = {
        "category": Category.INPUT_VALIDATION,
        "severity": Severity.MEDIUM,
        "confidence": Confidence.MEDIUM,
        "title": "Unvalidated user input",
        "description": "User input is passed directly to a database query.",
        "file": "src/db.py",
        "start_line": 10,
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_scan_result(findings: list[Finding] | None = None) -> ScanResult:
    return ScanResult(
        repo="acme/webapp",
        pr_number=42,
        commit_sha="deadbeef",
        ref="feature/new-endpoint",
        findings=findings or [],
    )


# ---------------------------------------------------------------------------
# Engine tests
# ---------------------------------------------------------------------------

class TestEngine:
    def test_analyse_returns_list(self):
        """analyse() returns a list of findings (empty for stubs)."""
        result = analyse([])
        assert isinstance(result, list)

    def test_analyse_with_files_returns_list(self):
        result = analyse(["src/app.py", "src/routes.py"])
        assert isinstance(result, list)

    def test_deduplicate_removes_duplicates(self):
        f = _make_finding(id="dup123")
        assert len(_deduplicate([f, f])) == 1

    def test_deduplicate_preserves_unique(self):
        f1 = _make_finding(id="aaa")
        f2 = _make_finding(id="bbb")
        assert len(_deduplicate([f1, f2])) == 2


# ---------------------------------------------------------------------------
# Formatter tests
# ---------------------------------------------------------------------------

class TestFormatter:
    def test_no_findings_message(self):
        result = _make_scan_result(findings=[])
        md = format_markdown(result)
        assert "No security findings" in md

    def test_header_present(self):
        md = format_markdown(_make_scan_result())
        assert "parity-zero Security Review" in md

    def test_findings_rendered(self):
        findings = [
            _make_finding(severity=Severity.HIGH, title="SQL Injection"),
            _make_finding(severity=Severity.LOW, title="Weak default"),
        ]
        md = format_markdown(_make_scan_result(findings=findings))
        assert "SQL Injection" in md
        assert "Weak default" in md
        assert "2 finding(s)" in md

    def test_recommendation_rendered(self):
        f = _make_finding(recommendation="Use parameterised queries.")
        md = format_markdown(_make_scan_result(findings=[f]))
        assert "parameterised queries" in md

    def test_severity_sections(self):
        findings = [
            _make_finding(severity=Severity.HIGH, title="High issue"),
            _make_finding(severity=Severity.MEDIUM, title="Medium issue"),
        ]
        md = format_markdown(_make_scan_result(findings=findings))
        assert "### HIGH" in md
        assert "### MEDIUM" in md

    def test_scan_metadata_in_footer(self):
        result = _make_scan_result()
        md = format_markdown(result)
        assert result.commit_sha[:7] in md
