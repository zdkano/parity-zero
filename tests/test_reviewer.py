"""Tests for the parity-zero reviewer components.

Phase 1: smoke tests validating the engine wiring, formatter output,
PR context parsing, changed-file discovery, and the orchestration flow.
Detection-specific tests will be added alongside real check
implementations.
"""

import io
import json
import os
import urllib.error

import pytest

from schemas.findings import (
    Category,
    Confidence,
    Decision,
    Finding,
    ScanResult,
    Severity,
)
from reviewer.engine import analyse, _deduplicate
from reviewer.formatter import format_markdown
from reviewer.action import _load_event_payload, get_pr_context, get_changed_files, mock_run


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


def _make_scan_result(findings: list[Finding] | None = None, **overrides) -> ScanResult:
    defaults = {
        "repo": "acme/webapp",
        "pr_number": 42,
        "commit_sha": "deadbeef",
        "ref": "feature/new-endpoint",
        "findings": findings if findings is not None else [],
    }
    defaults.update(overrides)
    return ScanResult(**defaults)


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

    def test_decision_badge_pass(self):
        result = _make_scan_result(findings=[])
        md = format_markdown(result)
        assert "✅ Pass" in md

    def test_decision_badge_warn(self):
        result = _make_scan_result(
            findings=[_make_finding()],
            decision=Decision.WARN,
        )
        md = format_markdown(result)
        assert "⚠️ Warn" in md

    def test_decision_badge_block(self):
        result = _make_scan_result(
            findings=[_make_finding()],
            decision=Decision.BLOCK,
        )
        md = format_markdown(result)
        assert "🚫 Block" in md

    def test_risk_score_in_header(self):
        result = _make_scan_result(findings=[], risk_score=45)
        md = format_markdown(result)
        assert "45/100" in md

    def test_risk_bar_zero(self):
        result = _make_scan_result(findings=[], risk_score=0)
        md = format_markdown(result)
        assert "0/100" in md

    def test_risk_bar_hundred(self):
        result = _make_scan_result(findings=[], risk_score=100)
        md = format_markdown(result)
        assert "100/100" in md

    def test_recommendations_section(self):
        findings = [
            _make_finding(title="Issue A", recommendation="Fix A."),
            _make_finding(title="Issue B", recommendation="Fix B."),
        ]
        md = format_markdown(_make_scan_result(findings=findings))
        assert "### Recommendations" in md
        assert "**Issue A:** Fix A." in md
        assert "**Issue B:** Fix B." in md

    def test_no_recommendations_section_when_none(self):
        findings = [_make_finding(recommendation=None)]
        md = format_markdown(_make_scan_result(findings=findings))
        assert "### Recommendations" not in md

    def test_footer_includes_decision(self):
        result = _make_scan_result(
            findings=[_make_finding()],
            decision=Decision.WARN,
        )
        md = format_markdown(result)
        # The footer line should include the decision value
        assert "Decision: warn" in md

    def test_footer_includes_risk_score(self):
        result = _make_scan_result(findings=[], risk_score=30)
        md = format_markdown(result)
        assert "Risk: 30" in md

    def test_no_findings_still_has_footer(self):
        result = _make_scan_result(findings=[])
        md = format_markdown(result)
        assert "---" in md
        assert result.scan_id[:12] in md


# ---------------------------------------------------------------------------
# Event payload loading tests
# ---------------------------------------------------------------------------

class TestLoadEventPayload:
    def test_missing_env_var_returns_empty(self, monkeypatch):
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        assert _load_event_payload() == {}

    def test_empty_env_var_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GITHUB_EVENT_PATH", "")
        assert _load_event_payload() == {}

    def test_nonexistent_file_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "missing.json"))
        assert _load_event_payload() == {}

    def test_malformed_json_returns_empty(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(bad))
        assert _load_event_payload() == {}

    def test_non_object_json_returns_empty(self, monkeypatch, tmp_path):
        arr = tmp_path / "array.json"
        arr.write_text("[1, 2, 3]", encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(arr))
        assert _load_event_payload() == {}

    def test_valid_payload_returned(self, monkeypatch, tmp_path):
        payload = {"action": "opened", "number": 7}
        f = tmp_path / "event.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(f))
        assert _load_event_payload() == payload

    def test_directory_path_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path))
        assert _load_event_payload() == {}


# ---------------------------------------------------------------------------
# PR context extraction tests
# ---------------------------------------------------------------------------

class TestGetPrContext:
    """Test get_pr_context() with real event payloads and env var fallbacks."""

    FULL_EVENT = {
        "action": "opened",
        "number": 99,
        "pull_request": {
            "number": 99,
            "head": {
                "sha": "abc1234567890",
                "ref": "feature/login",
            },
        },
        "repository": {
            "full_name": "acme/webapp",
        },
    }

    def _write_event(self, tmp_path, monkeypatch, payload):
        f = tmp_path / "event.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(f))

    def test_full_event_payload(self, monkeypatch, tmp_path):
        self._write_event(tmp_path, monkeypatch, self.FULL_EVENT)
        ctx = get_pr_context()
        assert ctx["repo"] == "acme/webapp"
        assert ctx["pr_number"] == 99
        assert ctx["commit_sha"] == "abc1234567890"
        assert ctx["ref"] == "feature/login"

    def test_fallback_to_env_vars(self, monkeypatch):
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
        monkeypatch.setenv("PR_NUMBER", "5")
        monkeypatch.setenv("GITHUB_SHA", "deadbeef1234")
        monkeypatch.setenv("GITHUB_HEAD_REF", "fix/bug")
        ctx = get_pr_context()
        assert ctx["repo"] == "org/repo"
        assert ctx["pr_number"] == 5
        assert ctx["commit_sha"] == "deadbeef1234"
        assert ctx["ref"] == "fix/bug"

    def test_event_overrides_env(self, monkeypatch, tmp_path):
        """Event payload takes priority over environment variables."""
        monkeypatch.setenv("GITHUB_REPOSITORY", "fallback/repo")
        monkeypatch.setenv("PR_NUMBER", "1")
        self._write_event(tmp_path, monkeypatch, self.FULL_EVENT)
        ctx = get_pr_context()
        assert ctx["repo"] == "acme/webapp"
        assert ctx["pr_number"] == 99

    def test_partial_event_uses_env_fallback(self, monkeypatch, tmp_path):
        """Missing fields in the event fall back to env vars."""
        partial = {"action": "opened", "repository": {"full_name": "org/app"}}
        self._write_event(tmp_path, monkeypatch, partial)
        monkeypatch.setenv("PR_NUMBER", "12")
        monkeypatch.setenv("GITHUB_SHA", "cafe1234")
        monkeypatch.setenv("GITHUB_HEAD_REF", "main")
        ctx = get_pr_context()
        assert ctx["repo"] == "org/app"
        assert ctx["pr_number"] == 12
        assert ctx["commit_sha"] == "cafe1234"
        assert ctx["ref"] == "main"

    def test_defaults_when_nothing_set(self, monkeypatch, tmp_path):
        for var in ("GITHUB_EVENT_PATH", "GITHUB_REPOSITORY", "PR_NUMBER",
                     "GITHUB_SHA", "GITHUB_HEAD_REF"):
            monkeypatch.delenv(var, raising=False)
        ctx = get_pr_context()
        assert ctx["repo"] == "unknown/unknown"
        assert ctx["pr_number"] == 0
        assert ctx["commit_sha"] == "0000000"
        assert ctx["ref"] == "unknown"

    def test_event_number_fallback(self, monkeypatch, tmp_path):
        """Top-level 'number' in event used when pull_request.number is absent."""
        event = {"number": 77, "repository": {"full_name": "x/y"}}
        self._write_event(tmp_path, monkeypatch, event)
        monkeypatch.setenv("GITHUB_SHA", "aaa1234")
        monkeypatch.setenv("GITHUB_HEAD_REF", "dev")
        ctx = get_pr_context()
        assert ctx["pr_number"] == 77

    def test_returns_correct_types(self, monkeypatch, tmp_path):
        self._write_event(tmp_path, monkeypatch, self.FULL_EVENT)
        ctx = get_pr_context()
        assert isinstance(ctx["repo"], str)
        assert isinstance(ctx["pr_number"], int)
        assert isinstance(ctx["commit_sha"], str)
        assert isinstance(ctx["ref"], str)


# ---------------------------------------------------------------------------
# Changed-file discovery tests
# ---------------------------------------------------------------------------

class TestGetChangedFiles:
    """Test get_changed_files() with mocked GitHub API responses."""

    def _mock_api_response(self, monkeypatch, body, status=200):
        """Replace urllib.request.urlopen with a mock returning *body*."""
        raw = json.dumps(body).encode("utf-8")

        class FakeResp:
            def read(self):
                return raw
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda req: FakeResp())

    def test_missing_context_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        assert get_changed_files("unknown/unknown", 0) == []
        assert get_changed_files("", 1) == []
        assert get_changed_files("acme/app", -1) == []

    def test_missing_token_returns_empty(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert get_changed_files("acme/app", 1) == []

    def test_filters_deleted_files(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        api_body = [
            {"filename": "src/app.py", "status": "modified"},
            {"filename": "src/old.py", "status": "removed"},
            {"filename": "src/new.py", "status": "added"},
        ]
        self._mock_api_response(monkeypatch, api_body)
        result = get_changed_files("acme/app", 1)
        assert "src/app.py" in result
        assert "src/new.py" in result
        assert "src/old.py" not in result

    def test_includes_renamed_files(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        api_body = [
            {"filename": "src/renamed.py", "status": "renamed"},
        ]
        self._mock_api_response(monkeypatch, api_body)
        result = get_changed_files("acme/app", 1)
        assert result == ["src/renamed.py"]

    def test_api_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        def raise_http_error(req):
            raise urllib.error.HTTPError(
                req.full_url, 403, "Forbidden", {}, io.BytesIO(b"")
            )

        monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
        result = get_changed_files("acme/app", 1)
        assert result == []

    def test_malformed_api_response_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        class FakeResp:
            def read(self):
                return b"not json"
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass

        monkeypatch.setattr("urllib.request.urlopen", lambda req: FakeResp())
        result = get_changed_files("acme/app", 1)
        assert result == []

    def test_empty_page_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        self._mock_api_response(monkeypatch, [])
        result = get_changed_files("acme/app", 1)
        assert result == []

    def test_non_list_response_returns_empty(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        self._mock_api_response(monkeypatch, {"error": "unexpected"})
        result = get_changed_files("acme/app", 1)
        assert result == []

    def test_entries_without_filename_skipped(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        api_body = [
            {"status": "modified"},
            {"filename": "", "status": "modified"},
            {"filename": "valid.py", "status": "added"},
        ]
        self._mock_api_response(monkeypatch, api_body)
        result = get_changed_files("acme/app", 1)
        assert result == ["valid.py"]

    def test_uses_github_api_url_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        monkeypatch.setenv("GITHUB_API_URL", "https://git.corp.example.com/api/v3")

        captured_urls = []

        class FakeResp:
            def read(self):
                return b"[]"
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass

        def capture_urlopen(req):
            captured_urls.append(req.full_url)
            return FakeResp()

        monkeypatch.setattr("urllib.request.urlopen", capture_urlopen)
        get_changed_files("acme/app", 1)
        assert captured_urls
        assert captured_urls[0].startswith("https://git.corp.example.com/api/v3/")


# ---------------------------------------------------------------------------
# Mock runner tests
# ---------------------------------------------------------------------------

class TestMockRun:
    """Test mock_run() produces valid reviewer output."""

    def test_returns_dict_with_expected_keys(self):
        output = mock_run()
        assert "result" in output
        assert "markdown" in output
        assert "json" in output

    def test_result_is_scan_result(self):
        output = mock_run()
        assert isinstance(output["result"], ScanResult)

    def test_result_has_findings(self):
        output = mock_run()
        assert len(output["result"].findings) > 0

    def test_result_has_decision(self):
        output = mock_run()
        assert output["result"].decision in (Decision.PASS, Decision.WARN, Decision.BLOCK)

    def test_result_has_risk_score(self):
        output = mock_run()
        assert 0 <= output["result"].risk_score <= 100

    def test_markdown_is_string(self):
        output = mock_run()
        assert isinstance(output["markdown"], str)
        assert len(output["markdown"]) > 0

    def test_markdown_contains_header(self):
        output = mock_run()
        assert "parity-zero Security Review" in output["markdown"]

    def test_markdown_contains_decision(self):
        output = mock_run()
        assert "Decision:" in output["markdown"]

    def test_markdown_contains_risk(self):
        output = mock_run()
        assert "/100" in output["markdown"]

    def test_json_is_valid(self):
        output = mock_run()
        parsed = json.loads(output["json"])
        assert isinstance(parsed, dict)

    def test_json_round_trips_to_scan_result(self):
        output = mock_run()
        restored = ScanResult.model_validate_json(output["json"])
        assert restored.repo == output["result"].repo
        assert restored.decision == output["result"].decision
        assert restored.risk_score == output["result"].risk_score
        assert len(restored.findings) == len(output["result"].findings)

    def test_json_has_risk_score(self):
        output = mock_run()
        parsed = json.loads(output["json"])
        assert "risk_score" in parsed
        assert isinstance(parsed["risk_score"], int)

    def test_findings_cover_multiple_severities(self):
        """mock_run() is designed to produce diverse findings for demo output."""
        output = mock_run()
        severities = {f.severity for f in output["result"].findings}
        assert len(severities) >= 2

    def test_findings_cover_multiple_categories(self):
        """mock_run() is designed to produce diverse findings for demo output."""
        output = mock_run()
        categories = {f.category for f in output["result"].findings}
        assert len(categories) >= 2

    def test_markdown_has_recommendations_section(self):
        output = mock_run()
        assert "### Recommendations" in output["markdown"]
