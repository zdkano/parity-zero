"""Tests for the AnthropicProvider and provider configuration (ADR-031).

Covers:
- AnthropicProvider interface conformance
- AnthropicProvider availability checks
- Anthropic Messages API request formatting
- Response parsing from Anthropic content blocks
- Graceful failure on network/timeout/invalid response
- Provider configuration resolution for anthropic
- Config-enabled vs disabled behavior
- Fallback when provider config is missing or provider call fails
- Preservation of current reviewer flow
- No scoring impact from live provider output
- No ScanResult contract change
- Compatibility with existing providers
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.models import PRContent, PullRequestContext, RepoSecurityProfile
from reviewer.providers import (
    AnthropicProvider,
    CandidateNote,
    DisabledProvider,
    GitHubModelsProvider,
    MockProvider,
    OpenAIProvider,
    ReasoningProvider,
    ReasoningRequest,
    ReasoningResponse,
)
from reviewer.provider_config import resolve_provider
from schemas.findings import Category, Decision, ScanResult


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


def _mock_anthropic_response(content_text: str, status_code: int = 200):
    """Create a mock httpx response matching Anthropic Messages API shape."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "id": "msg_test123",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": content_text},
        ],
        "model": "claude-sonnet-4-20250514",
        "stop_reason": "end_turn",
    }
    mock_resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp,
        )
    return mock_resp


# ======================================================================
# AnthropicProvider interface tests
# ======================================================================


class TestAnthropicProviderInterface:
    """Verify AnthropicProvider conforms to the ReasoningProvider protocol."""

    def test_implements_provider_interface(self):
        provider = AnthropicProvider(api_key="test-key")
        assert isinstance(provider, ReasoningProvider)

    def test_name_is_anthropic(self):
        provider = AnthropicProvider(api_key="test-key")
        assert provider.name == "anthropic"

    def test_is_available_with_api_key(self):
        provider = AnthropicProvider(api_key="test-key")
        assert provider.is_available()

    def test_is_not_available_without_api_key(self):
        provider = AnthropicProvider(api_key="")
        assert not provider.is_available()

    def test_is_not_available_with_no_args(self):
        provider = AnthropicProvider()
        assert not provider.is_available()

    def test_reason_returns_reasoning_response(self):
        """Even when unavailable, reason() returns a valid ReasoningResponse."""
        provider = AnthropicProvider(api_key="")
        req = _make_request()
        resp = provider.reason(req)
        assert isinstance(resp, ReasoningResponse)

    def test_reason_returns_empty_when_unavailable(self):
        provider = AnthropicProvider(api_key="")
        req = _make_request()
        resp = provider.reason(req)
        assert not resp.has_content
        assert resp.candidate_notes == []
        assert resp.candidate_findings == []
        assert resp.provider_name == "anthropic"
        assert not resp.is_from_live_provider

    def test_default_model(self):
        provider = AnthropicProvider(api_key="key")
        assert provider._model == "claude-sonnet-4-20250514"

    def test_custom_model(self):
        provider = AnthropicProvider(api_key="key", model="claude-3-haiku-20240307")
        assert provider._model == "claude-3-haiku-20240307"

    def test_custom_endpoint(self):
        provider = AnthropicProvider(
            api_key="key", endpoint="https://custom.anthropic.example.com/"
        )
        assert provider._endpoint == "https://custom.anthropic.example.com"

    def test_default_endpoint(self):
        provider = AnthropicProvider(api_key="key")
        assert provider._endpoint == "https://api.anthropic.com"


# ======================================================================
# Anthropic API call tests (mocked HTTP)
# ======================================================================


class TestAnthropicProviderCall:
    """Test AnthropicProvider.reason() with mocked HTTP calls."""

    @patch("reviewer.providers._httpx_mod")
    def test_successful_call_returns_notes(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response(
            '[{"title": "Auth check missing", "summary": "Missing auth on /admin", "paths": ["auth.py"], "confidence": "medium"}]'
        )
        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert resp.is_from_live_provider
        assert resp.provider_name == "anthropic"
        assert len(resp.candidate_notes) == 1
        assert "Missing auth on /admin" in resp.candidate_notes[0]
        assert resp.candidate_findings == []

    @patch("reviewer.providers._httpx_mod")
    def test_successful_call_returns_structured_notes(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response(
            json.dumps([
                {"title": "Auth issue", "summary": "Missing auth check", "paths": ["auth.py"], "confidence": "medium"},
                {"title": "Config note", "summary": "Debug mode enabled", "paths": ["config.py"], "confidence": "low"},
            ])
        )
        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert len(resp.structured_notes) == 2
        assert resp.structured_notes[0].title == "Auth issue"
        assert resp.structured_notes[0].source == "anthropic"
        assert resp.structured_notes[1].title == "Config note"

    @patch("reviewer.providers._httpx_mod")
    def test_successful_call_sends_correct_payload(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response("[]")
        provider = AnthropicProvider(
            api_key="test-key", model="claude-3-haiku-20240307"
        )
        req = _make_request()
        provider.reason(req)

        mock_httpx.post.assert_called_once()
        call_kwargs = mock_httpx.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")

        assert payload["model"] == "claude-3-haiku-20240307"
        assert "system" in payload
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["role"] == "user"
        assert payload["max_tokens"] == 1024
        assert headers["x-api-key"] == "test-key"
        assert "anthropic-version" in headers

    @patch("reviewer.providers._httpx_mod")
    def test_sends_to_correct_endpoint(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response("[]")
        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        provider.reason(req)

        call_args = mock_httpx.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert url == "https://api.anthropic.com/v1/messages"

    @patch("reviewer.providers._httpx_mod")
    def test_network_error_returns_empty(self, mock_httpx):
        mock_httpx.post.side_effect = Exception("Connection refused")
        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []
        assert resp.provider_name == "anthropic"

    @patch("reviewer.providers._httpx_mod")
    def test_timeout_returns_empty(self, mock_httpx):
        import httpx
        mock_httpx.post.side_effect = httpx.TimeoutException("Timeout")
        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_http_error_returns_empty(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response("", status_code=500)
        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_http_429_returns_empty(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response("", status_code=429)
        provider = AnthropicProvider(api_key="test-key")
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

        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_empty_content_returns_empty(self, mock_httpx):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [{"type": "text", "text": ""}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_resp

        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert not resp.is_from_live_provider
        assert resp.candidate_notes == []

    @patch("reviewer.providers._httpx_mod")
    def test_does_not_produce_findings(self, mock_httpx):
        """Phase 1: provider does not produce candidate findings."""
        mock_httpx.post.return_value = _mock_anthropic_response(
            '[{"title": "Some note", "summary": "Detail", "paths": [], "confidence": "low"}]'
        )
        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)
        assert resp.candidate_findings == []

    @patch("reviewer.providers._httpx_mod")
    def test_multiple_content_blocks(self, mock_httpx):
        """Anthropic can return multiple text blocks; we concatenate them."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [
                {"type": "text", "text": '[{"title": "Note 1", "summary": "First"},'},
                {"type": "text", "text": ' {"title": "Note 2", "summary": "Second"}]'},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_httpx.post.return_value = mock_resp

        provider = AnthropicProvider(api_key="test-key")
        req = _make_request()
        resp = provider.reason(req)

        assert resp.is_from_live_provider
        assert len(resp.structured_notes) == 2


# ======================================================================
# Anthropic provider config resolution tests
# ======================================================================


class TestAnthropicProviderConfig:
    """Test provider configuration resolution for anthropic."""

    def test_anthropic_with_api_key(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-test-123",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, AnthropicProvider)
            assert provider.name == "anthropic"
            assert provider.is_available()

    def test_anthropic_without_api_key_falls_back(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "anthropic",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)

    def test_anthropic_with_empty_api_key_falls_back(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, DisabledProvider)

    def test_anthropic_with_custom_model(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "PARITY_REASONING_MODEL": "claude-3-haiku-20240307",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, AnthropicProvider)
            assert provider._model == "claude-3-haiku-20240307"

    def test_case_insensitive_anthropic(self):
        with patch.dict(os.environ, {
            "PARITY_REASONING_PROVIDER": "Anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-test",
        }, clear=True):
            provider = resolve_provider()
            assert isinstance(provider, AnthropicProvider)


# ======================================================================
# Pipeline integration tests
# ======================================================================


class TestAnthropicPipelineIntegration:
    """Verify AnthropicProvider integrates correctly with the pipeline."""

    @patch("reviewer.providers._httpx_mod")
    def test_provider_notes_flow_through_engine(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response(
            '[{"title": "Security note", "summary": "Security note from Anthropic", "paths": ["src/auth/login.py"], "confidence": "medium"}]'
        )
        provider = AnthropicProvider(api_key="test-key")
        ctx = _make_ctx(files={"src/auth/login.py": "auth code"})
        result = analyse(ctx, provider=provider)

        assert isinstance(result, AnalysisResult)
        assert any(
            "Security note from Anthropic" in n
            for n in result.reasoning_notes
        )

    @patch("reviewer.providers._httpx_mod")
    def test_provider_does_not_add_findings(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response(
            '[{"title": "Issue", "summary": "This looks like a security issue", "paths": [], "confidence": "medium"}]'
        )
        provider = AnthropicProvider(api_key="test-key")
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result_provider = analyse(ctx, provider=provider)
        result_default = analyse(ctx)

        assert len(result_provider.findings) == len(result_default.findings)

    @patch("reviewer.providers._httpx_mod")
    def test_provider_does_not_affect_scoring(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response(
            '[{"title": "SSL note", "summary": "SSL verification is disabled", "paths": ["config.py"], "confidence": "medium"}]'
        )
        provider = AnthropicProvider(api_key="test-key")
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})

        result_provider = analyse(ctx, provider=provider)
        result_default = analyse(ctx)

        _, score_provider = derive_decision_and_risk(result_provider.findings)
        _, score_default = derive_decision_and_risk(result_default.findings)
        assert score_provider == score_default

    @patch("reviewer.providers._httpx_mod")
    def test_provider_failure_does_not_break_pipeline(self, mock_httpx):
        mock_httpx.post.side_effect = Exception("Connection refused")
        provider = AnthropicProvider(api_key="test-key")
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        result = analyse(ctx, provider=provider)

        assert isinstance(result, AnalysisResult)
        assert len(result.findings) > 0
        categories = [f.category for f in result.findings]
        assert Category.INSECURE_CONFIGURATION in categories

    @patch("reviewer.providers._httpx_mod")
    def test_provider_timeout_does_not_break_pipeline(self, mock_httpx):
        import httpx
        mock_httpx.post.side_effect = httpx.TimeoutException("Timeout")
        provider = AnthropicProvider(api_key="test-key")
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=provider)

        assert isinstance(result, AnalysisResult)
        assert isinstance(result.reasoning_notes, list)


# ======================================================================
# ScanResult contract stability tests
# ======================================================================


class TestScanResultContractWithAnthropic:
    """Verify ScanResult JSON contract is unchanged with AnthropicProvider."""

    @patch("reviewer.providers._httpx_mod")
    def test_scan_result_shape_unchanged(self, mock_httpx):
        mock_httpx.post.return_value = _mock_anthropic_response(
            '[{"title": "Note", "summary": "Note from Anthropic", "paths": [], "confidence": "low"}]'
        )
        provider = AnthropicProvider(api_key="test-key")
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
        assert "anthropic" not in json.dumps(data)


# ======================================================================
# Compatibility with existing providers
# ======================================================================


class TestAnthropicProviderCompatibility:
    """Verify AnthropicProvider coexists with existing providers."""

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

    def test_anthropic_provider_contract_matches(self):
        """AnthropicProvider follows same response contract as others."""
        provider = AnthropicProvider(api_key="")
        req = ReasoningRequest()
        resp = provider.reason(req)

        assert isinstance(resp, ReasoningResponse)
        assert isinstance(resp.candidate_notes, list)
        assert isinstance(resp.candidate_findings, list)
        assert isinstance(resp.provider_name, str)
        assert isinstance(resp.is_from_live_provider, bool)

    @pytest.mark.parametrize("provider_cls", [
        DisabledProvider, MockProvider, GitHubModelsProvider, AnthropicProvider, OpenAIProvider,
    ])
    def test_all_providers_implement_interface(self, provider_cls):
        if provider_cls == GitHubModelsProvider:
            provider = provider_cls(token="")
        elif provider_cls in (AnthropicProvider, OpenAIProvider):
            provider = provider_cls(api_key="")
        else:
            provider = provider_cls()
        assert hasattr(provider, "reason")
        assert hasattr(provider, "is_available")
        assert hasattr(provider, "name")
        assert isinstance(provider.name, str)
        assert len(provider.name) > 0
