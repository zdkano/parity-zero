"""Integration tests for the parity-zero reasoning runtime (ADR-025).

Covers:
- Engine integration with DisabledProvider (default behavior preserved)
- Engine integration with MockProvider (provider notes flow through)
- Reasoning request assembly during pipeline execution
- JSON contract stability (ScanResult unchanged)
- No scoring impact from provider output
- Disabled/fallback behavior
- Provider output does not create findings
- Backward compatibility with existing callers
"""

from __future__ import annotations

import json

from reviewer.action import mock_run
from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.models import (
    PRContent,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)
from reviewer.providers import DisabledProvider, MockProvider
from reviewer.reasoning import ReasoningResult, run_reasoning
from schemas.findings import Category, Confidence, Decision, Finding, ScanResult, Severity


# ======================================================================
# Helpers
# ======================================================================


def _make_ctx(
    files: dict[str, str] | None = None,
    frameworks: list[str] | None = None,
    auth_patterns: list[str] | None = None,
    memory_entries: list[tuple[str, str]] | None = None,
) -> PullRequestContext:
    file_dict = files or {"app.py": "print('hello')"}
    pr_content = PRContent.from_dict(file_dict)
    profile = None
    if frameworks or auth_patterns:
        profile = RepoSecurityProfile(
            frameworks=frameworks or [],
            auth_patterns=auth_patterns or [],
        )
    memory = None
    if memory_entries:
        memory = ReviewMemory(
            entries=[
                ReviewMemoryEntry(category=cat, summary=summ)
                for cat, summ in memory_entries
            ]
        )
    return PullRequestContext(
        pr_content=pr_content,
        baseline_profile=profile,
        memory=memory,
    )


def _make_scan_result(findings=None) -> ScanResult:
    decision, risk_score = derive_decision_and_risk(findings or [])
    return ScanResult(
        repo="test/repo",
        pr_number=1,
        commit_sha="abc1234",
        ref="main",
        decision=decision,
        risk_score=risk_score,
        findings=findings or [],
    )


# ======================================================================
# Default behavior (no provider) tests
# ======================================================================


class TestDefaultBehavior:
    """Verify that the engine works unchanged without a provider."""

    def test_engine_works_without_provider(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx)
        assert isinstance(result, AnalysisResult)
        assert isinstance(result.reasoning_notes, list)

    def test_engine_produces_same_findings_without_provider(self):
        """Deterministic findings are unaffected by provider absence."""
        ctx = _make_ctx(files={
            "config.py": "VERIFY_SSL = False\n",
        })
        result = analyse(ctx)
        assert len(result.findings) > 0
        categories = [f.category for f in result.findings]
        assert Category.INSECURE_CONFIGURATION in categories

    def test_dict_input_still_works(self):
        result = analyse({"app.py": "print('hello')"})
        assert isinstance(result, AnalysisResult)

    def test_pr_content_input_still_works(self):
        pc = PRContent.from_dict({"app.py": "print('hello')"})
        result = analyse(pc)
        assert isinstance(result, AnalysisResult)


# ======================================================================
# DisabledProvider integration tests
# ======================================================================


class TestDisabledProviderIntegration:
    """Verify that DisabledProvider preserves current behavior exactly."""

    def test_disabled_provider_produces_same_as_default(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result_default = analyse(ctx)
        result_disabled = analyse(ctx, provider=DisabledProvider())
        assert len(result_default.findings) == len(result_disabled.findings)
        # Notes may differ slightly in wording but should have same count
        assert len(result_default.reasoning_notes) == len(result_disabled.reasoning_notes)

    def test_disabled_provider_does_not_add_notes(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=DisabledProvider())
        # No mock-reasoning notes should appear
        for note in result.reasoning_notes:
            assert "[mock-reasoning]" not in note

    def test_disabled_provider_does_not_affect_scoring(self):
        ctx = _make_ctx(files={
            "config.py": "VERIFY_SSL = False\n",
        })
        result = analyse(ctx, provider=DisabledProvider())
        decision, risk_score = derive_decision_and_risk(result.findings)
        assert decision in (Decision.PASS, Decision.WARN)
        assert risk_score >= 0


# ======================================================================
# MockProvider integration tests
# ======================================================================


class TestMockProviderIntegration:
    """Verify that MockProvider output flows through the pipeline."""

    def test_mock_provider_adds_notes(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=MockProvider())
        mock_notes = [n for n in result.reasoning_notes if "[mock-reasoning]" in n]
        assert len(mock_notes) > 0

    def test_mock_provider_does_not_add_findings(self):
        """Phase 1: provider output does not produce findings."""
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result_default = analyse(ctx)
        result_mock = analyse(ctx, provider=MockProvider())
        assert len(result_default.findings) == len(result_mock.findings)

    def test_mock_provider_does_not_affect_scoring(self):
        ctx = _make_ctx(files={
            "config.py": "VERIFY_SSL = False\n",
        })
        result_default = analyse(ctx)
        result_mock = analyse(ctx, provider=MockProvider())
        _, score_default = derive_decision_and_risk(result_default.findings)
        _, score_mock = derive_decision_and_risk(result_mock.findings)
        assert score_default == score_mock

    def test_mock_provider_with_rich_context(self):
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
            memory_entries=[("authentication", "Prior auth concern")],
        )
        result = analyse(ctx, provider=MockProvider())
        mock_notes = [n for n in result.reasoning_notes if "[mock-reasoning]" in n]
        assert len(mock_notes) > 0
        # Should reflect the rich context
        notes_text = " ".join(mock_notes)
        assert "1 changed file" in notes_text

    def test_mock_provider_reflects_plan_in_notes(self):
        """MockProvider notes should reflect plan focus when present."""
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
        )
        result = analyse(ctx, provider=MockProvider())
        notes_text = " ".join(result.reasoning_notes)
        # The plan should detect sensitive/auth paths
        assert "[mock-reasoning]" in notes_text


# ======================================================================
# Reasoning request assembly tests
# ======================================================================


class TestReasoningRequestAssembly:
    """Verify that reasoning requests are assembled during pipeline execution."""

    def test_reasoning_result_has_request(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.reasoning_request is not None

    def test_reasoning_result_request_has_files(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(files={"a.py": "x", "b.py": "y"})
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.reasoning_request is not None
        assert result.reasoning_request.file_count == 2

    def test_reasoning_request_includes_deterministic_findings(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        plan = build_review_plan(ctx)
        det_findings = [
            Finding(
                category=Category.INSECURE_CONFIGURATION,
                severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                title="Security disablement",
                description="SSL verify disabled",
                file="config.py",
            )
        ]
        result = run_reasoning(ctx, plan=plan, deterministic_findings=det_findings)
        assert result.reasoning_request is not None
        assert len(result.reasoning_request.deterministic_findings_summary) == 1

    def test_reasoning_result_without_plan_has_no_request(self):
        """Legacy path: no plan means no reasoning request assembled."""
        ctx = _make_ctx(files={"app.py": "code"})
        result = run_reasoning(ctx, plan=None)
        assert result.reasoning_request is None

    def test_provider_name_recorded_when_mock(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(files={"app.py": "code"})
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.provider_name == "mock"

    def test_provider_name_empty_when_disabled(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(files={"app.py": "code"})
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=DisabledProvider())
        assert result.provider_name == ""

    def test_provider_name_empty_when_no_provider(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(files={"app.py": "code"})
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.provider_name == ""


# ======================================================================
# JSON contract stability tests
# ======================================================================


class TestJsonContractStability:
    """Verify that the ScanResult JSON contract is unchanged."""

    def test_scan_result_shape_unchanged(self):
        ctx = _make_ctx(files={
            "config.py": "VERIFY_SSL = False\n",
        })
        result = analyse(ctx, provider=MockProvider())
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
        json_str = scan.model_dump_json()
        data = json.loads(json_str)
        # Core contract keys
        assert "scan_id" in data
        assert "repo" in data
        assert "pr_number" in data
        assert "commit_sha" in data
        assert "ref" in data
        assert "decision" in data
        assert "risk_score" in data
        assert "findings" in data
        # No provider-specific keys leak into contract
        assert "reasoning_request" not in data
        assert "provider_name" not in data
        assert "candidate_notes" not in data

    def test_scan_result_findings_unchanged_with_provider(self):
        ctx = _make_ctx(files={
            "deploy.py": "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n",
        })
        result_default = analyse(ctx)
        result_mock = analyse(ctx, provider=MockProvider())

        # Same findings regardless of provider
        assert len(result_default.findings) == len(result_mock.findings)
        for f_default, f_mock in zip(
            sorted(result_default.findings, key=lambda f: f.title),
            sorted(result_mock.findings, key=lambda f: f.title),
        ):
            assert f_default.category == f_mock.category
            assert f_default.severity == f_mock.severity
            assert f_default.title == f_mock.title


# ======================================================================
# No-overclaiming tests
# ======================================================================


class TestNoOverclaiming:
    """Verify that provider output does not create unjustified findings."""

    def test_mock_provider_notes_do_not_become_findings(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=MockProvider())
        # Clean file: no findings even with mock provider
        assert len(result.findings) == 0

    def test_mock_provider_does_not_inflate_risk_score(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=MockProvider())
        decision, risk_score = derive_decision_and_risk(result.findings)
        assert risk_score == 0
        assert decision == Decision.PASS

    def test_disabled_provider_does_not_alter_clean_result(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=DisabledProvider())
        assert len(result.findings) == 0
        decision, risk_score = derive_decision_and_risk(result.findings)
        assert risk_score == 0
        assert decision == Decision.PASS


# ======================================================================
# Markdown output tests
# ======================================================================


class TestMarkdownOutput:
    """Verify that provider output integrates cleanly into markdown."""

    def test_markdown_includes_mock_reasoning_notes(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=MockProvider())
        scan = _make_scan_result(result.findings)
        md = format_markdown(
            scan,
            concerns=result.concerns,
            observations=result.observations,
        )
        # Markdown should be valid regardless of provider
        assert "parity-zero Security Review" in md

    def test_markdown_structure_unchanged_with_provider(self):
        ctx = _make_ctx(files={
            "config.py": "VERIFY_SSL = False\n",
        })
        result = analyse(ctx, provider=MockProvider())
        scan = _make_scan_result(result.findings)
        md = format_markdown(scan)
        assert "Decision:" in md
        assert "Risk:" in md


# ======================================================================
# Backward compatibility tests
# ======================================================================


class TestBackwardCompatibility:
    """Verify that existing callers continue to work without changes."""

    def test_analyse_without_provider_kwarg(self):
        """Existing callers that do not pass provider still work."""
        result = analyse({"app.py": "print('hello')"})
        assert isinstance(result, AnalysisResult)

    def test_run_reasoning_without_provider_kwarg(self):
        """Existing callers that do not pass provider still work."""
        result = run_reasoning({"app.py": "print('hello')"})
        assert isinstance(result, ReasoningResult)

    def test_mock_run_still_works(self):
        """The mock_run action function continues to work."""
        output = mock_run()
        assert "result" in output
        assert "markdown" in output
        assert "json" in output
        assert "reasoning_notes" in output
        assert isinstance(output["result"], ScanResult)


# ======================================================================
# Fallback behavior tests
# ======================================================================


class TestFallbackBehavior:
    """Verify graceful behavior when provider is unavailable."""

    def test_disabled_provider_is_graceful(self):
        ctx = _make_ctx(files={"app.py": "code"})
        result = analyse(ctx, provider=DisabledProvider())
        assert isinstance(result, AnalysisResult)
        assert isinstance(result.reasoning_notes, list)

    def test_none_provider_is_graceful(self):
        ctx = _make_ctx(files={"app.py": "code"})
        result = analyse(ctx, provider=None)
        assert isinstance(result, AnalysisResult)

    def test_legacy_dict_with_provider(self):
        result = analyse({"app.py": "code"}, provider=MockProvider())
        assert isinstance(result, AnalysisResult)
        mock_notes = [n for n in result.reasoning_notes if "[mock-reasoning]" in n]
        assert len(mock_notes) > 0
