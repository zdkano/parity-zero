"""Tests for the parity-zero reasoning provider interface (ADR-025).

Covers:
- ReasoningRequest model construction and properties
- ReasoningResponse model construction and properties
- DisabledProvider behavior (default, returns empty response)
- MockProvider behavior (predictable structured output)
- Provider interface contract (is_available, name, reason)
- No scoring impact from provider output
"""

from __future__ import annotations

import pytest

from reviewer.providers import (
    DisabledProvider,
    MockProvider,
    ReasoningProvider,
    ReasoningRequest,
    ReasoningResponse,
)


# ======================================================================
# ReasoningRequest model tests
# ======================================================================


class TestReasoningRequest:
    """Tests for the ReasoningRequest data model."""

    def test_empty_request(self):
        req = ReasoningRequest()
        assert req.file_count == 0
        assert not req.has_plan_context
        assert not req.has_baseline_context
        assert not req.has_memory_context
        assert req.changed_files_summary == []
        assert req.plan_focus_areas == []
        assert req.plan_flags == []
        assert req.plan_guidance == []
        assert req.baseline_frameworks == []
        assert req.baseline_auth_patterns == []
        assert req.memory_categories == []
        assert req.memory_entries == []
        assert req.existing_concerns == []
        assert req.existing_observations == []
        assert req.deterministic_findings_summary == []

    def test_file_count_reflects_summaries(self):
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "a.py", "review_reason": "changed_file", "focus_areas": ""},
                {"path": "b.py", "review_reason": "sensitive_path", "focus_areas": "secrets"},
            ]
        )
        assert req.file_count == 2

    def test_has_plan_context_with_focus_areas(self):
        req = ReasoningRequest(plan_focus_areas=["authentication"])
        assert req.has_plan_context

    def test_has_plan_context_with_flags(self):
        req = ReasoningRequest(plan_flags=["touches_sensitive_path"])
        assert req.has_plan_context

    def test_has_baseline_context_with_frameworks(self):
        req = ReasoningRequest(baseline_frameworks=["fastapi"])
        assert req.has_baseline_context

    def test_has_baseline_context_with_auth_patterns(self):
        req = ReasoningRequest(baseline_auth_patterns=["jwt"])
        assert req.has_baseline_context

    def test_has_memory_context_with_categories(self):
        req = ReasoningRequest(memory_categories=["secrets"])
        assert req.has_memory_context

    def test_has_memory_context_with_entries(self):
        req = ReasoningRequest(
            memory_entries=[{"category": "secrets", "summary": "Prior finding"}]
        )
        assert req.has_memory_context

    def test_no_plan_context_when_empty(self):
        req = ReasoningRequest()
        assert not req.has_plan_context

    def test_no_baseline_context_when_empty(self):
        req = ReasoningRequest()
        assert not req.has_baseline_context

    def test_no_memory_context_when_empty(self):
        req = ReasoningRequest()
        assert not req.has_memory_context

    def test_full_request_construction(self):
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "auth_area", "focus_areas": "authentication"},
            ],
            plan_focus_areas=["authentication", "authorization"],
            plan_flags=["touches_auth_path"],
            plan_guidance=["Review auth boundary"],
            baseline_frameworks=["django"],
            baseline_auth_patterns=["jwt", "oauth"],
            memory_categories=["authentication"],
            memory_entries=[{"category": "authentication", "summary": "Prior auth issue"}],
            existing_concerns=[{"category": "authentication", "title": "Auth concern", "summary": "desc"}],
            existing_observations=[{"path": "auth.py", "title": "Auth obs", "summary": "desc"}],
            deterministic_findings_summary=[{"category": "secrets", "title": "Hardcoded key", "file": "config.py"}],
        )
        assert req.file_count == 1
        assert req.has_plan_context
        assert req.has_baseline_context
        assert req.has_memory_context
        assert len(req.existing_concerns) == 1
        assert len(req.existing_observations) == 1
        assert len(req.deterministic_findings_summary) == 1


# ======================================================================
# ReasoningResponse model tests
# ======================================================================


class TestReasoningResponse:
    """Tests for the ReasoningResponse data model."""

    def test_empty_response(self):
        resp = ReasoningResponse()
        assert not resp.has_content
        assert resp.candidate_notes == []
        assert resp.candidate_findings == []
        assert resp.provider_name == ""
        assert resp.is_from_live_provider is False

    def test_response_with_notes(self):
        resp = ReasoningResponse(
            candidate_notes=["Note 1", "Note 2"],
            provider_name="mock",
        )
        assert resp.has_content
        assert len(resp.candidate_notes) == 2

    def test_response_with_findings(self):
        resp = ReasoningResponse(
            candidate_findings=[{"category": "secrets", "title": "test"}],
        )
        assert resp.has_content

    def test_response_is_not_live_by_default(self):
        resp = ReasoningResponse(provider_name="mock")
        assert not resp.is_from_live_provider


# ======================================================================
# DisabledProvider tests
# ======================================================================


class TestDisabledProvider:
    """Tests for the DisabledProvider (default no-op provider)."""

    def test_is_not_available(self):
        provider = DisabledProvider()
        assert not provider.is_available()

    def test_name_is_disabled(self):
        provider = DisabledProvider()
        assert provider.name == "disabled"

    def test_reason_returns_empty_response(self):
        provider = DisabledProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "auth_area", "focus_areas": "authentication"},
            ],
            plan_focus_areas=["authentication"],
        )
        resp = provider.reason(req)
        assert isinstance(resp, ReasoningResponse)
        assert not resp.has_content
        assert resp.candidate_notes == []
        assert resp.candidate_findings == []
        assert resp.provider_name == "disabled"
        assert not resp.is_from_live_provider

    def test_reason_ignores_rich_request(self):
        """DisabledProvider returns empty regardless of input richness."""
        provider = DisabledProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "sensitive_auth", "focus_areas": "authentication"},
            ],
            plan_focus_areas=["authentication", "authorization"],
            plan_flags=["touches_sensitive_path", "touches_auth_path"],
            baseline_frameworks=["django", "fastapi"],
            memory_categories=["authentication"],
        )
        resp = provider.reason(req)
        assert not resp.has_content

    def test_implements_provider_interface(self):
        provider = DisabledProvider()
        assert isinstance(provider, ReasoningProvider)


# ======================================================================
# MockProvider tests
# ======================================================================


class TestMockProvider:
    """Tests for the MockProvider (testing/local development provider)."""

    def test_is_available(self):
        provider = MockProvider()
        assert provider.is_available()

    def test_name_is_mock(self):
        provider = MockProvider()
        assert provider.name == "mock"

    def test_reason_returns_structured_response(self):
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "a.py", "review_reason": "changed_file", "focus_areas": ""},
            ],
        )
        resp = provider.reason(req)
        assert isinstance(resp, ReasoningResponse)
        assert resp.has_content
        assert resp.provider_name == "mock"
        assert not resp.is_from_live_provider

    def test_reason_includes_file_count(self):
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "a.py", "review_reason": "changed_file", "focus_areas": ""},
                {"path": "b.py", "review_reason": "changed_file", "focus_areas": ""},
                {"path": "c.py", "review_reason": "changed_file", "focus_areas": ""},
            ],
        )
        resp = provider.reason(req)
        # Cross-file interaction note references file count and paths.
        assert any("3 files" in n for n in resp.candidate_notes)

    def test_reason_reflects_plan_context(self):
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "auth_area", "focus_areas": "authentication"},
            ],
            plan_focus_areas=["authentication", "authorization"],
        )
        resp = provider.reason(req)
        assert any("authentication" in n for n in resp.candidate_notes)

    def test_reason_reflects_baseline_context(self):
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "app.py", "review_reason": "changed_file", "focus_areas": ""},
            ],
            baseline_frameworks=["django"],
        )
        resp = provider.reason(req)
        assert any("django" in n for n in resp.candidate_notes)

    def test_reason_reflects_memory_context(self):
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "app.py", "review_reason": "changed_file", "focus_areas": ""},
            ],
            memory_categories=["secrets"],
        )
        resp = provider.reason(req)
        assert any("secrets" in n for n in resp.candidate_notes)

    def test_reason_reflects_deterministic_findings(self):
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "app.py", "review_reason": "changed_file", "focus_areas": ""},
            ],
            deterministic_findings_summary=[
                {"category": "secrets", "title": "Hardcoded key", "file": "config.py"},
            ],
        )
        resp = provider.reason(req)
        assert any("deterministic" in n.lower() for n in resp.candidate_notes)

    def test_reason_produces_no_findings(self):
        """Phase 1: MockProvider does not produce candidate findings."""
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "auth_area", "focus_areas": "authentication"},
            ],
            plan_focus_areas=["authentication"],
        )
        resp = provider.reason(req)
        assert resp.candidate_findings == []

    def test_reason_with_empty_request(self):
        provider = MockProvider()
        req = ReasoningRequest()
        resp = provider.reason(req)
        # Empty request produces no notes — correct quiet behavior.
        assert not resp.has_content
        assert len(resp.candidate_notes) == 0

    def test_implements_provider_interface(self):
        provider = MockProvider()
        assert isinstance(provider, ReasoningProvider)


# ======================================================================
# Provider interface contract tests
# ======================================================================


class TestProviderContract:
    """Tests that providers conform to the ReasoningProvider protocol."""

    @pytest.mark.parametrize("provider_cls", [DisabledProvider, MockProvider])
    def test_has_reason_method(self, provider_cls):
        provider = provider_cls()
        assert hasattr(provider, "reason")
        assert callable(provider.reason)

    @pytest.mark.parametrize("provider_cls", [DisabledProvider, MockProvider])
    def test_has_is_available_method(self, provider_cls):
        provider = provider_cls()
        assert hasattr(provider, "is_available")
        result = provider.is_available()
        assert isinstance(result, bool)

    @pytest.mark.parametrize("provider_cls", [DisabledProvider, MockProvider])
    def test_has_name_property(self, provider_cls):
        provider = provider_cls()
        assert hasattr(provider, "name")
        assert isinstance(provider.name, str)
        assert len(provider.name) > 0

    @pytest.mark.parametrize("provider_cls", [DisabledProvider, MockProvider])
    def test_reason_returns_reasoning_response(self, provider_cls):
        provider = provider_cls()
        req = ReasoningRequest()
        resp = provider.reason(req)
        assert isinstance(resp, ReasoningResponse)

    @pytest.mark.parametrize("provider_cls", [DisabledProvider, MockProvider])
    def test_response_is_not_live(self, provider_cls):
        """Phase 1: no live provider implementations exist."""
        provider = provider_cls()
        req = ReasoningRequest()
        resp = provider.reason(req)
        assert not resp.is_from_live_provider
