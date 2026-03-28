"""Tests for the GitHubModelsProvider and provider configuration (ADR-026).

Covers:
- GitHubModelsProvider interface conformance
- GitHubModelsProvider availability checks
- Prompt formatting from ReasoningRequest
- Response parsing (JSON array, fallback)
- Graceful failure on network/timeout/invalid response
- Provider configuration resolution
- Config-enabled vs disabled behavior
- Fallback when provider config is missing or provider call fails
- Preservation of current reviewer flow
- No scoring impact from live provider output
- No ScanResult contract change
- Compatibility with existing MockProvider and DisabledProvider behavior
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.models import PRContent, PullRequestContext, RepoSecurityProfile
from reviewer.providers import (
    CandidateNote,
    DisabledProvider,
    GitHubModelsProvider,
    MockProvider,
    ReasoningProvider,
    ReasoningRequest,
    ReasoningResponse,
    _format_user_prompt,
    _parse_candidate_notes,
)
from reviewer.provider_config import resolve_provider
from schemas.findings import Category, Confidence, Decision, Finding, ScanResult, Severity


# ======================================================================
# Helpers
# ======================================================================


def _make_ctx(
    files: dict[str, str] | None = None,
    frameworks: list[str] | None = None,
) -> PullRequestContext:
    file_dict = files or {"app.py": "print('hello')"}
    pr_content = PRContent.from_dict(file_dict)
    profile = None
    if frameworks:
        profile = RepoSecurityProfile(frameworks=frameworks)
    return PullRequestContext(pr_content=pr_content, baseline_profile=profile)


def _make_request(**kwargs) -> ReasoningRequest:
    defaults = {
        "changed_files_summary": [
            {"path": "app.py", "review_reason": "changed_file", "focus_areas": ""},
        ],
    }
    defaults.update(kwargs)
    return ReasoningRequest(**defaults)


def _mock_httpx_response(content: str, status_code: int = 200):
    """Create a mock httpx response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": content,
                }
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp,
        )
    return mock_resp


# ======================================================================
# GitHubModelsProvider interface tests
# ======================================================================


class TestGitHubModelsProviderInterface:
    """Verify GitHubModelsProvider conforms to the ReasoningProvider protocol."""

    def test_implements_provider_interface(self):
        provider = GitHubModelsProvider(token="test-token")
        assert isinstance(provider, ReasoningProvider)

    def test_name_is_github_models(self):
        provider = GitHubModelsProvider(token="test-token")
        assert provider.name == "github-models"

    def test_is_available_with_token(self):
        provider = GitHubModelsProvider(token="test-token")
        assert provider.is_available()

    def test_is_not_available_without_token(self):
        provider = GitHubModelsProvider(token="")
        assert not provider.is_available()

    def test_is_not_available_with_empty_token(self):
        provider = GitHubModelsProvider()
        assert not provider.is_available()

    def test_reason_returns_reasoning_response(self):
        """Even when unavailable, reason() returns a valid ReasoningResponse."""
        provider = GitHubModelsProvider(token="")
        req = _make_request()
        resp = provider.reason(req)
        assert isinstance(resp, ReasoningResponse)

    def test_reason_returns_empty_when_unavailable(self):
        provider = GitHubModelsProvider(token="")
        req = _make_request()
        resp = provider.reason(req)
        assert not resp.has_content
        assert resp.candidate_notes == []
        assert resp.candidate_findings == []
        assert resp.provider_name == "github-models"
        assert not resp.is_from_live_provider

    def test_default_model(self):
        provider = GitHubModelsProvider(token="tok")
        assert provider._model == "openai/gpt-4o-mini"

    def test_custom_model(self):
        provider = GitHubModelsProvider(token="tok", model="openai/gpt-4o")
        assert provider._model == "openai/gpt-4o"

    def test_custom_endpoint(self):
        provider = GitHubModelsProvider(
            token="tok", endpoint="https://custom.endpoint.com/"
        )
        assert provider._endpoint == "https://custom.endpoint.com"


# ======================================================================
# Prompt formatting tests
# ======================================================================


class TestPromptFormatting:
    """Verify that ReasoningRequest is formatted into a useful prompt."""

    def test_empty_request_produces_fallback(self):
        req = ReasoningRequest()
        prompt = _format_user_prompt(req)
        assert "No context available" in prompt

    def test_changed_files_in_prompt(self):
        req = _make_request(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "auth_area", "focus_areas": "authentication"},
                {"path": "config.py", "review_reason": "changed_file", "focus_areas": ""},
            ]
        )
        prompt = _format_user_prompt(req)
        assert "auth.py" in prompt
        assert "config.py" in prompt
        assert "auth_area" in prompt

    def test_plan_context_in_prompt(self):
        req = _make_request(
            plan_focus_areas=["authentication", "secrets"],
            plan_flags=["touches_sensitive_path"],
            plan_guidance=["Check auth boundaries"],
        )
        prompt = _format_user_prompt(req)
        assert "authentication" in prompt
        assert "secrets" in prompt
        assert "touches_sensitive_path" in prompt
        assert "Check auth boundaries" in prompt

    def test_baseline_context_in_prompt(self):
        req = _make_request(
            baseline_frameworks=["django", "fastapi"],
            baseline_auth_patterns=["jwt"],
        )
        prompt = _format_user_prompt(req)
        assert "django" in prompt
        assert "fastapi" in prompt
        assert "jwt" in prompt

    def test_memory_context_in_prompt(self):
        req = _make_request(memory_categories=["secrets", "authentication"])
        prompt = _format_user_prompt(req)
        assert "secrets" in prompt
        assert "authentication" in prompt

    def test_existing_concerns_in_prompt(self):
        req = _make_request(
            existing_concerns=[
                {"category": "auth", "title": "Missing auth", "summary": "No auth check"},
            ]
        )
        prompt = _format_user_prompt(req)
        assert "Missing auth" in prompt

    def test_existing_observations_in_prompt(self):
        req = _make_request(
            existing_observations=[
                {"path": "auth.py", "title": "Auth obs", "summary": "Worth reviewing"},
            ]
        )
        prompt = _format_user_prompt(req)
        assert "Auth obs" in prompt

    def test_deterministic_findings_in_prompt(self):
        req = _make_request(
            deterministic_findings_summary=[
                {"category": "secrets", "title": "Hardcoded key", "file": "config.py"},
            ]
        )
        prompt = _format_user_prompt(req)
        assert "Hardcoded key" in prompt
        assert "config.py" in prompt


# ======================================================================
# Response parsing tests
# ======================================================================


class TestResponseParsing:
    """Verify parsing of model response text into candidate notes."""

    def test_parse_valid_json_string_array(self):
        raw = '["Note one", "Note two", "Note three"]'
        notes = _parse_candidate_notes(raw)
        assert len(notes) == 3
        assert all(isinstance(n, CandidateNote) for n in notes)
        assert notes[0].summary == "Note one"
        assert notes[1].summary == "Note two"
        assert notes[2].summary == "Note three"

    def test_parse_structured_json_objects(self):
        raw = json.dumps([
            {"title": "Auth issue", "summary": "Missing auth check", "paths": ["auth.py"], "confidence": "medium"},
            {"title": "Config note", "summary": "Debug mode enabled", "paths": ["config.py"], "confidence": "low"},
        ])
        notes = _parse_candidate_notes(raw, provider_name="github-models")
        assert len(notes) == 2
        assert notes[0].title == "Auth issue"
        assert notes[0].summary == "Missing auth check"
        assert notes[0].related_paths == ["auth.py"]
        assert notes[0].confidence == "medium"
        assert notes[0].source == "github-models"
        assert notes[1].title == "Config note"

    def test_parse_empty_array(self):
        raw = "[]"
        notes = _parse_candidate_notes(raw)
        assert notes == []

    def test_parse_json_with_surrounding_text(self):
        raw = 'Here are my observations:\n["Note one", "Note two"]\nEnd.'
        notes = _parse_candidate_notes(raw)
        summaries = [n.summary for n in notes]
        assert "Note one" in summaries
        assert "Note two" in summaries

    def test_parse_non_json_fallback(self):
        raw = "- This is a security observation about auth.\n- Another observation about config."
        notes = _parse_candidate_notes(raw)
        assert len(notes) >= 1
        assert all(isinstance(n, CandidateNote) for n in notes)

    def test_parse_empty_string(self):
        raw = ""
        notes = _parse_candidate_notes(raw)
        assert notes == []

    def test_parse_filters_empty_strings(self):
        raw = '["Note one", "", "  ", "Note two"]'
        notes = _parse_candidate_notes(raw)
        assert len(notes) == 2
        summaries = [n.summary for n in notes]
        assert "Note one" in summaries
        assert "Note two" in summaries

    def test_parse_limits_notes(self):
        raw = json.dumps([f"Note {i}" for i in range(30)])
        notes = _parse_candidate_notes(raw)
        assert len(notes) <= 10

    def test_parse_non_string_items_ignored(self):
        raw = '["Valid note", 42, true, "Another valid note"]'
        notes = _parse_candidate_notes(raw)
        assert len(notes) == 2
        summaries = [n.summary for n in notes]
        assert "Valid note" in summaries
        assert "Another valid note" in summaries

    def test_parse_mixed_objects_and_strings(self):
        raw = json.dumps([
            {"title": "Structured note", "summary": "Detail here"},
            "Simple string note",
        ])
        notes = _parse_candidate_notes(raw)
        assert len(notes) == 2
        assert notes[0].title == "Structured note"
        assert notes[1].summary == "Simple string note"

    def test_parse_object_confidence_clamped(self):
        """Confidence values outside low/medium are clamped to low."""
        raw = json.dumps([
            {"title": "Note", "summary": "Detail", "confidence": "high"},
        ])
        notes = _parse_candidate_notes(raw)
        assert notes[0].confidence == "low"

    def test_parse_provider_name_propagated(self):
        raw = '["A note"]'
        notes = _parse_candidate_notes(raw, provider_name="test-provider")
        assert notes[0].source == "test-provider"


# ======================================================================
# Live provider call tests (mocked HTTP)
# ======================================================================


class TestGitHubModelsProviderCall:
    """Test GitHubModelsProvider.reason() with mocked HTTP calls."""

    @patch("reviewer.providers._httpx_mod")
    def test_successful_call_returns_notes(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            '["Auth check missing on /admin endpoint", "Config uses debug mode"]'
        )
        provider = GitHubModelsProvider(token="test-token")
        req = _make_request()
        resp = provider.reason(req)

        assert resp.is_from_live_provider
        assert resp.provider_name == "github-models"
        assert len(resp.candidate_notes) == 2
        assert "Auth check missing" in resp.candidate_notes[0]
        assert resp.candidate_findings == []

    @patch("reviewer.providers._httpx_mod")
    def test_successful_call_sends_correct_payload(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response("[]")
        provider = GitHubModelsProvider(
            token="test-token", model="openai/gpt-4o"
        )
        req = _make_request()
        provider.reason(req)

        mock_httpx.post.assert_called_once()
        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["model"] == "openai/gpt-4o"
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][1]["role"] == "user"

    @patch("reviewer.providers._httpx_mod")
    def test_network_error_returns_empty(self, mock_httpx):
        mock_httpx.post.side_effect = Exception("Connection refused")
        provider = GitHubModelsProvider(token="test-token")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []
        assert resp.provider_name == "github-models"

    @patch("reviewer.providers._httpx_mod")
    def test_timeout_returns_empty(self, mock_httpx):
        import httpx
        mock_httpx.post.side_effect = httpx.TimeoutException("Timeout")
        provider = GitHubModelsProvider(token="test-token")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_http_error_returns_empty(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response("", status_code=500)
        provider = GitHubModelsProvider(token="test-token")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_invalid_json_response_returns_empty(self, mock_httpx):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"unexpected": "shape"}
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_resp

        provider = GitHubModelsProvider(token="test-token")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_empty_content_returns_empty(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response("")
        provider = GitHubModelsProvider(token="test-token")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_does_not_produce_findings(self, mock_httpx):
        """Phase 1: provider does not produce candidate findings."""
        mock_httpx.post.return_value = _mock_httpx_response(
            '["Some security note"]'
        )
        provider = GitHubModelsProvider(token="test-token")
        req = _make_request()
        resp = provider.reason(req)
        assert resp.candidate_findings == []


# ======================================================================
# Provider configuration resolution tests
# ======================================================================


class TestProviderConfig:
    """Test provider configuration resolution from environment."""

    def test_default_is_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)
            assert provider.name == "disabled"

    def test_explicit_disabled(self):
        with patch.dict(os.environ, {"PARITY_REASONING_PROVIDER": "disabled"}, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)

    def test_github_models_with_token(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "github-models",
            "GITHUB_TOKEN": "test-token-123",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, GitHubModelsProvider)
            assert provider.name == "github-models"
            assert provider.is_available()

    def test_github_models_without_token_falls_back(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "github-models",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)

    def test_github_models_with_custom_model(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "github-models",
            "GITHUB_TOKEN": "test-token",
            "PARITY_REASONING_MODEL": "openai/gpt-4o",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, GitHubModelsProvider)
            assert provider._model == "openai/gpt-4o"

    def test_unknown_provider_falls_back_to_disabled(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "unknown-provider",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)

    def test_empty_provider_is_disabled(self):
        with patch.dict(os.environ, {"PARITY_REASONING_PROVIDER": ""}, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)

    def test_case_insensitive_provider_name(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "GitHub-Models",
            "GITHUB_TOKEN": "test-token",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, GitHubModelsProvider)


# ======================================================================
# Pipeline integration tests (no scoring impact)
# ======================================================================


class TestPipelineIntegration:
    """Verify GitHubModelsProvider integrates correctly with the pipeline."""

    @patch("reviewer.providers._httpx_mod")
    def test_provider_notes_flow_through_engine(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            '["Security note from GitHub Models"]'
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=provider)

        assert isinstance(result, AnalysisResult)
        assert any(
            "Security note from GitHub Models" in n
            for n in result.reasoning_notes
        )

    @patch("reviewer.providers._httpx_mod")
    def test_provider_does_not_add_findings(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            '["This looks like a security issue"]'
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result_provider = analyse(ctx, provider=provider)
        result_default = analyse(ctx)

        assert len(result_provider.findings) == len(result_default.findings)

    @patch("reviewer.providers._httpx_mod")
    def test_provider_does_not_affect_scoring(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            '["SSL verification is disabled"]'
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})

        result_provider = analyse(ctx, provider=provider)
        result_default = analyse(ctx)

        _, score_provider = derive_decision_and_risk(result_provider.findings)
        _, score_default = derive_decision_and_risk(result_default.findings)
        assert score_provider == score_default

    @patch("reviewer.providers._httpx_mod")
    def test_provider_failure_does_not_break_pipeline(self, mock_httpx):
        mock_httpx.post.side_effect = Exception("Connection refused")
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        result = analyse(ctx, provider=provider)

        assert isinstance(result, AnalysisResult)
        # Deterministic findings still work
        assert len(result.findings) > 0
        categories = [f.category for f in result.findings]
        assert Category.INSECURE_CONFIGURATION in categories

    @patch("reviewer.providers._httpx_mod")
    def test_provider_timeout_does_not_break_pipeline(self, mock_httpx):
        import httpx
        mock_httpx.post.side_effect = httpx.TimeoutException("Timeout")
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=provider)

        assert isinstance(result, AnalysisResult)
        assert isinstance(result.reasoning_notes, list)


# ======================================================================
# ScanResult contract stability tests
# ======================================================================


class TestScanResultContractWithGitHubModels:
    """Verify ScanResult JSON contract is unchanged with GitHubModelsProvider."""

    @patch("reviewer.providers._httpx_mod")
    def test_scan_result_shape_unchanged(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            '["Note from live provider"]'
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        result = analyse(ctx, provider=provider)
        decision, risk_score = derive_decision_and_risk(result.findings)

        scan = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
            decision=decision,
            risk_score=risk_score,
            findings=result.findings,
        )
        data = json.loads(scan.model_dump_json())

        # Core contract keys present
        assert "scan_id" in data
        assert "repo" in data
        assert "pr_number" in data
        assert "commit_sha" in data
        assert "decision" in data
        assert "risk_score" in data
        assert "findings" in data

        # No provider-specific keys leak into contract
        assert "reasoning_request" not in data
        assert "provider_name" not in data
        assert "candidate_notes" not in data
        assert "github-models" not in json.dumps(data)


# ======================================================================
# Compatibility with existing providers
# ======================================================================


class TestProviderCompatibility:
    """Verify GitHubModelsProvider coexists with existing providers."""

    @pytest.mark.parametrize("provider_cls,expected_name", [
        (DisabledProvider, "disabled"),
        (MockProvider, "mock"),
    ])
    def test_existing_providers_unchanged(self, provider_cls, expected_name):
        provider = provider_cls()
        assert provider.name == expected_name
        assert isinstance(provider, ReasoningProvider)
        req = ReasoningRequest()
        resp = provider.reason(req)
        assert isinstance(resp, ReasoningResponse)

    def test_github_models_provider_contract_matches(self):
        """GitHubModelsProvider follows same response contract as others."""
        provider = GitHubModelsProvider(token="")
        req = ReasoningRequest()
        resp = provider.reason(req)

        # Same contract shape as DisabledProvider / MockProvider
        assert isinstance(resp, ReasoningResponse)
        assert isinstance(resp.candidate_notes, list)
        assert isinstance(resp.candidate_findings, list)
        assert isinstance(resp.provider_name, str)
        assert isinstance(resp.is_from_live_provider, bool)

    @pytest.mark.parametrize("provider_cls", [
        DisabledProvider, MockProvider, GitHubModelsProvider,
    ])
    def test_all_providers_implement_interface(self, provider_cls):
        if provider_cls == GitHubModelsProvider:
            provider = provider_cls(token="")
        else:
            provider = provider_cls()
        assert hasattr(provider, "reason")
        assert hasattr(provider, "is_available")
        assert hasattr(provider, "name")
        assert isinstance(provider.name, str)
        assert len(provider.name) > 0


# ======================================================================
# Action entry point integration test
# ======================================================================


class TestActionIntegration:
    """Verify the action entry point wires provider correctly."""

    def test_mock_run_still_works(self):
        """Existing mock_run continues to work without live credentials."""
        from reviewer.action import mock_run
        output = mock_run()
        assert "result" in output
        assert "markdown" in output
        assert "json" in output
        assert isinstance(output["result"], ScanResult)

    def test_resolve_provider_default_in_action(self):
        """Default provider resolution in action context is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)
