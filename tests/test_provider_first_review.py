"""Tests proving the provider-first review shift (ADR-045).

This module validates that:
1. When provider review is present, it becomes the main rendered review surface.
2. Heuristic concern/observation sections are suppressed when provider review is present.
3. Endpoint/auth-sensitive scenarios produce provider-led review output.
4. Low-signal scenarios remain quiet.
5. Tests/fixtures are less likely to dominate review output.
6. Findings remain unchanged as authoritative/scoring inputs.
7. Provider output still does not appear in ScanResult.
8. Provider output still does not affect scoring.
9. Deterministic findings still drive decision/risk_score.
10. Provider review remains candidate/non-authoritative.
"""

from __future__ import annotations

import json

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.models import (
    PullRequestContext,
    PRContent,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)
from reviewer.provider_review import ProviderReview, ProviderReviewItem
from reviewer.providers import CandidateNote, MockProvider, DisabledProvider
from reviewer.validation import find_scenario, all_scenarios, REALISTIC_SCENARIOS
from reviewer.validation.runner import run_scenario
from schemas.findings import Decision, ScanResult


def _build_scan_result(analysis: AnalysisResult) -> ScanResult:
    """Build a ScanResult from an AnalysisResult, as the action layer does."""
    decision, risk = derive_decision_and_risk(analysis.findings)
    return ScanResult(
        repo="test/repo",
        pr_number=1,
        commit_sha="0000000",
        ref="main",
        decision=decision,
        risk_score=risk,
        findings=analysis.findings,
    )


def _render_markdown(analysis: AnalysisResult) -> str:
    """Build markdown from AnalysisResult including provider review."""
    sr = _build_scan_result(analysis)
    return format_markdown(
        sr,
        concerns=analysis.concerns,
        observations=analysis.observations,
        provider_notes=analysis.provider_notes,
        provider_review=analysis.provider_review,
    )


# ======================================================================
# Helpers
# ======================================================================

def _make_auth_context() -> PullRequestContext:
    """Auth-sensitive PR context that triggers provider review."""
    return PullRequestContext(
        pr_content=PRContent.from_dict({
            "src/auth/login.py": (
                "from flask import request, jsonify\n"
                "@app.route('/login', methods=['POST'])\n"
                "def login():\n"
                "    username = request.json['username']\n"
                "    password = request.json['password']\n"
                "    user = db.query(User).filter_by(username=username).first()\n"
                "    if user and user.check_password(password):\n"
                "        session['user_id'] = user.id\n"
                "        return jsonify({'status': 'ok'})\n"
                "    return jsonify({'error': 'invalid'}), 401\n"
            ),
        }),
        baseline_profile=RepoSecurityProfile(
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/auth/"],
            auth_patterns=["session", "login", "password"],
        ),
    )


def _make_low_signal_context() -> PullRequestContext:
    """Low-signal PR context — docs/tests only."""
    return PullRequestContext(
        pr_content=PRContent.from_dict({
            "README.md": "# Updated docs\n\nMinor formatting change.\n",
            "CHANGELOG.md": "## v1.2.3\n- Fixed typos.\n",
        }),
    )


def _make_test_only_context() -> PullRequestContext:
    """Test-files-only PR context — should remain quiet."""
    return PullRequestContext(
        pr_content=PRContent.from_dict({
            "tests/test_utils.py": (
                "import pytest\n"
                "from src.utils import format_date\n"
                "def test_format_date():\n"
                "    assert format_date('2024-01-01') == 'Jan 1, 2024'\n"
            ),
            "tests/test_helpers.py": (
                "def test_helper_function():\n"
                "    assert True\n"
            ),
        }),
    )


# ======================================================================
# Part B: Provider output is the main review surface
# ======================================================================


class TestProviderBecomesMainReviewSurface:
    """When provider review is present, it is the dominant review section."""

    def test_auth_scenario_shows_provider_review_section(self):
        """Auth-sensitive mock scenario should have Provider Security Review."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        assert "Provider Security Review" in md

    def test_provider_review_is_above_footer(self):
        """Provider review section appears between findings and footer."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        pr_idx = md.find("Provider Security Review")
        footer_idx = md.find("---\n*Scan:")
        assert pr_idx > 0
        assert footer_idx > pr_idx

    def test_provider_review_items_have_evidence(self):
        """Provider review items should carry evidence from code analysis."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        if result.provider_review and result.provider_review.has_items:
            for item in result.provider_review.items:
                # Most items from mock should have evidence or summary
                assert item.summary, f"Item {item.title!r} has no summary"


class TestProviderReviewSuppressesHeuristics:
    """When provider review is present, heuristic sections are suppressed."""

    def test_concerns_suppressed_when_provider_review_present(self):
        """Concerns section should not appear when provider review has items."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        # Verify concerns exist internally
        assert len(result.concerns) > 0, "Expected concerns to be generated"
        # But suppressed in markdown
        md = _render_markdown(result)
        assert "Review Concerns" not in md
        assert "Provider Security Review" in md

    def test_observations_suppressed_when_provider_review_present(self):
        """Observations section should not appear when provider review has items."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        # Verify observations exist internally
        assert len(result.observations) > 0, "Expected observations to be generated"
        # But suppressed in markdown
        md = _render_markdown(result)
        assert "Review Observations" not in md
        assert "Provider Security Review" in md

    def test_concerns_shown_as_fallback_without_provider(self):
        """Without provider, concerns should still appear in markdown."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=DisabledProvider())
        md = _render_markdown(result)
        if result.concerns:
            assert "Review Concerns" in md

    def test_observations_shown_as_fallback_without_provider(self):
        """Without provider, observations should still appear in markdown."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=DisabledProvider())
        md = _render_markdown(result)
        if result.observations:
            assert "Review Observations" in md

    def test_legacy_provider_notes_suppressed_by_review(self):
        """Legacy provider notes section must not appear when structured review present."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        assert "Additional Review Notes" not in md

    def test_one_main_reviewer_voice(self):
        """With provider review, there should be exactly one review section."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        # Count section headers (###)
        section_headers = [
            line for line in md.split("\n")
            if line.startswith("### ")
        ]
        review_sections = [
            h for h in section_headers
            if any(kw in h for kw in [
                "Provider Security Review",
                "Review Concerns",
                "Review Observations",
                "Additional Review Notes",
            ])
        ]
        # Should have at most one review section (provider review)
        assert len(review_sections) <= 1, (
            f"Expected at most 1 review section, got {len(review_sections)}: "
            f"{review_sections}"
        )


# ======================================================================
# Part A: Low-signal scenarios remain quiet
# ======================================================================


class TestLowSignalRemainsQuiet:
    """Low-signal PRs should not produce noisy output even with provider-first model."""

    def test_docs_only_quiet(self):
        """Docs-only PR produces no review content."""
        ctx = _make_low_signal_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        assert "No security findings" in md
        assert "Provider Security Review" not in md
        assert "Review Concerns" not in md
        assert "Review Observations" not in md

    def test_test_only_quiet(self):
        """Test-files-only PR produces no review content."""
        ctx = _make_test_only_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        assert "No security findings" in md
        assert "Provider Security Review" not in md
        assert len(result.findings) == 0

    def test_low_signal_markdown_concise(self):
        """Low-signal markdown should be brief."""
        ctx = _make_low_signal_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        assert len(md) < 500, f"Low-signal markdown too long: {len(md)} chars"


# ======================================================================
# Part D.9: Trust boundaries preserved
# ======================================================================


class TestTrustBoundariesPreserved:
    """Provider output must not leak into ScanResult, scoring, or findings."""

    def test_provider_review_not_in_scan_result_json(self):
        """ScanResult JSON must not contain provider review items."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        sr = _build_scan_result(result)
        sr_json = json.loads(sr.model_dump_json())
        assert "provider_review" not in sr_json
        assert "provider_notes" not in sr_json
        assert "concerns" not in sr_json
        assert "observations" not in sr_json

    def test_provider_does_not_affect_scoring(self):
        """Decision and risk_score must be the same with/without provider."""
        ctx = _make_auth_context()
        result_mock = analyse(ctx, provider=MockProvider())
        result_disabled = analyse(ctx, provider=DisabledProvider())
        assert _build_scan_result(result_mock).decision == _build_scan_result(result_disabled).decision
        assert _build_scan_result(result_mock).risk_score == _build_scan_result(result_disabled).risk_score

    def test_provider_does_not_create_findings(self):
        """Provider output must never create findings."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        # All findings should be from deterministic checks
        for f in result.findings:
            assert f.category.value in {
                "secrets", "insecure_configuration",
                "authentication", "authorization",
                "input_validation", "dependency_risk",
            }
        # Findings should be same set with/without provider
        result_disabled = analyse(ctx, provider=DisabledProvider())
        assert len(result.findings) == len(result_disabled.findings)

    def test_decision_derived_from_findings_only(self):
        """Decision must be derivable from findings alone."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        expected_decision, expected_risk = derive_decision_and_risk(result.findings)
        assert _build_scan_result(result).decision == expected_decision
        assert _build_scan_result(result).risk_score == expected_risk

    def test_provider_review_items_capped_confidence(self):
        """Provider review items must never have 'high' confidence."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        if result.provider_review and result.provider_review.has_items:
            for item in result.provider_review.items:
                assert item.confidence in ("low", "medium"), (
                    f"Item {item.title!r} has confidence {item.confidence!r}"
                )

    def test_provider_review_remains_non_authoritative(self):
        """Provider review items are clearly marked as non-authoritative in markdown."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        if "Provider Security Review" in md:
            assert "not proven findings" in md or "do not affect" in md


# ======================================================================
# Realistic scenario validation
# ======================================================================


class TestRealisticProviderFirstShift:
    """Realistic scenarios should reflect the provider-first shift."""

    def test_auth_scenarios_show_provider_review(self):
        """Auth-focused realistic scenarios should show provider review when mock."""
        for s in REALISTIC_SCENARIOS:
            if "auth" in s.tags and s.provider_mode == "mock":
                result = run_scenario(s)
                md = result.markdown
                assert "Provider Security Review" in md, (
                    f"Realistic scenario {s.id!r} with mock provider missing "
                    f"Provider Security Review section"
                )

    def test_auth_scenarios_suppress_heuristic_sections(self):
        """Auth mock scenarios should NOT show heuristic sections."""
        for s in REALISTIC_SCENARIOS:
            if "auth" in s.tags and s.provider_mode == "mock":
                result = run_scenario(s)
                md = result.markdown
                if result.analysis.provider_review and result.analysis.provider_review.has_items:
                    assert "Review Concerns" not in md, (
                        f"Scenario {s.id!r}: concerns should be suppressed "
                        f"when provider review present"
                    )
                    assert "Review Observations" not in md, (
                        f"Scenario {s.id!r}: observations should be suppressed "
                        f"when provider review present"
                    )

    def test_low_signal_scenarios_remain_quiet(self):
        """Low-signal realistic scenarios should stay quiet."""
        for s in REALISTIC_SCENARIOS:
            if "low-signal" in s.tags:
                result = run_scenario(s)
                md = result.markdown
                assert "Provider Security Review" not in md
                assert "No security findings" in md
                assert len(result.analysis.findings) == 0

    def test_deterministic_scenarios_still_detect(self):
        """Deterministic scenarios still produce findings."""
        for s in REALISTIC_SCENARIOS:
            if "deterministic" in s.tags and "no-findings" not in s.tags:
                result = run_scenario(s)
                assert len(result.analysis.findings) > 0, (
                    f"Scenario {s.id!r} tagged deterministic but no findings"
                )

    def test_trust_boundaries_across_realistic_corpus(self):
        """Trust boundaries hold across all realistic scenarios."""
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            sr = _build_scan_result(result.analysis)
            expected_decision, expected_risk = derive_decision_and_risk(
                result.analysis.findings
            )
            assert sr.decision == expected_decision, (
                f"Scenario {s.id!r}: decision mismatch"
            )
            assert sr.risk_score == expected_risk, (
                f"Scenario {s.id!r}: risk_score mismatch"
            )


class TestSyntheticProviderFirstShift:
    """Synthetic scenarios should reflect the provider-first shift."""

    def test_mock_scenarios_show_provider_review(self):
        """Scenarios with mock provider and provider-value should show provider review."""
        for s in all_scenarios():
            if s.provider_mode == "mock" and s.provider_value_expected:
                result = run_scenario(s)
                # Provider review should be present if gate invoked
                if (result.analysis.provider_review
                        and result.analysis.provider_review.has_items):
                    assert "Provider Security Review" in result.markdown, (
                        f"Scenario {s.id!r}: expected Provider Security Review"
                    )

    def test_mock_scenarios_suppress_heuristics_when_provider_present(self):
        """Mock scenarios with provider review should suppress heuristic sections."""
        for s in all_scenarios():
            if s.provider_mode == "mock":
                result = run_scenario(s)
                if (result.analysis.provider_review
                        and result.analysis.provider_review.has_items):
                    md = result.markdown
                    assert "Review Concerns" not in md, (
                        f"Scenario {s.id!r}: concerns visible but provider review present"
                    )
                    assert "Review Observations" not in md, (
                        f"Scenario {s.id!r}: observations visible but provider review present"
                    )

    def test_disabled_scenarios_still_show_heuristics(self):
        """Disabled-provider scenarios should still show heuristic sections as fallback."""
        for s in all_scenarios():
            if s.provider_mode == "disabled":
                result = run_scenario(s)
                # Heuristic sections should appear if generated
                if result.analysis.concerns:
                    assert "Review Concerns" in result.markdown, (
                        f"Scenario {s.id!r}: concerns generated but not in markdown"
                    )
                if result.analysis.observations:
                    assert "Review Observations" in result.markdown, (
                        f"Scenario {s.id!r}: observations generated but not in markdown"
                    )


# ======================================================================
# Output quality: fewer stacked voices
# ======================================================================


class TestOutputQualityProviderFirst:
    """The output should feel like one main reviewer, not several stacked."""

    def test_no_redundant_review_sections_with_provider(self):
        """When provider review is present, at most one review-style section exists."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        review_section_keywords = [
            "Review Concerns",
            "Review Observations",
            "Additional Review Notes",
            "Provider Security Review",
        ]
        found_sections = [kw for kw in review_section_keywords if kw in md]
        assert len(found_sections) <= 1, (
            f"Multiple review sections found: {found_sections}"
        )

    def test_provider_review_describes_code_not_just_flags(self):
        """Provider review items should have substantive summaries."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        if result.provider_review and result.provider_review.has_items:
            for item in result.provider_review.items:
                assert len(item.summary) >= 15, (
                    f"Item {item.title!r} summary too short: {item.summary!r}"
                )

    def test_markdown_concise_with_provider(self):
        """Markdown with provider review should not be excessively long."""
        ctx = _make_auth_context()
        result = analyse(ctx, provider=MockProvider())
        md = _render_markdown(result)
        assert len(md) < 5000, (
            f"Markdown with provider review too long: {len(md)} chars"
        )


# ======================================================================
# Comparison: provider-first visible in evaluation
# ======================================================================


class TestComparisonReflectsShift:
    """Comparison output should reflect the provider-first shift."""

    def test_comparison_shows_provider_section_in_mock(self):
        """Mock mode should produce provider review section in auth scenarios."""
        s = find_scenario("auth-sensitive")
        assert s is not None
        # Run with mock
        from reviewer.validation.runner import run_scenario as rs
        result = rs(s)
        assert "Provider Security Review" in result.markdown

    def test_comparison_disabled_mode_has_heuristic_sections(self):
        """Disabled mode should show heuristic sections for auth scenarios."""
        s = find_scenario("sensitive-config")
        assert s is not None
        result = run_scenario(s)
        # Sensitive-config is disabled provider, should show heuristics
        if result.analysis.concerns:
            assert "Review Concerns" in result.markdown
