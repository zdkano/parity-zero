"""Tests for the provider invocation gating mechanism (ADR-029).

Covers:
1. Provider invoked when rich/security-relevant context is present
2. Provider skipped when context is weak
3. Gating reasons are stable and explainable
4. Disabled provider behavior unchanged
5. No scoring or contract changes
6. Pipeline remains stable in both invoke and skip cases
7. Gate result is recorded in ReasoningResult
8. Integration with engine (analyse) end-to-end
"""

from __future__ import annotations

import json

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.models import (
    PRContent,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewBundle,
    ReviewBundleItem,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewPlan,
)
from reviewer.planner import build_review_plan
from reviewer.provider_gate import ProviderGateResult, evaluate_provider_gate
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


def _rich_ctx() -> PullRequestContext:
    """Context with sensitive + auth paths — should invoke provider."""
    return _make_ctx(
        files={"src/auth/login.py": "auth code", "src/config/settings.py": "config"},
        frameworks=["django"],
        auth_patterns=["jwt"],
        memory_entries=[("authentication", "Prior auth finding")],
    )


def _weak_ctx() -> PullRequestContext:
    """Context with plain files — should skip provider."""
    return _make_ctx(files={"app.py": "print('hello')", "utils.py": "x = 1"})


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
# ProviderGateResult model tests
# ======================================================================


class TestProviderGateResult:
    """Tests for the ProviderGateResult data model."""

    def test_default_is_skip(self):
        result = ProviderGateResult()
        assert result.should_invoke is False
        assert result.reasons == []

    def test_invoke_result(self):
        result = ProviderGateResult(
            should_invoke=True,
            reasons=["invoke: sensitive paths touched: 2"],
        )
        assert result.should_invoke is True
        assert len(result.reasons) == 1

    def test_skip_result(self):
        result = ProviderGateResult(
            should_invoke=False,
            reasons=["skip: no sensitive paths touched"],
        )
        assert result.should_invoke is False
        assert "skip:" in result.reasons[0]

    def test_result_is_frozen(self):
        result = ProviderGateResult(should_invoke=True, reasons=["test"])
        try:
            result.should_invoke = False  # type: ignore[misc]
            assert False, "Should have raised"
        except AttributeError:
            pass


# ======================================================================
# evaluate_provider_gate — invoke cases
# ======================================================================


class TestGateInvokeCases:
    """Tests that provider invocation is triggered for rich/security-relevant context."""

    def test_invoke_when_sensitive_paths_touched(self):
        plan = ReviewPlan(sensitive_paths_touched=["src/config/settings.py"])
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is True
        assert any("sensitive paths" in r for r in result.reasons)

    def test_invoke_when_auth_paths_touched(self):
        plan = ReviewPlan(auth_paths_touched=["src/auth/login.py"])
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is True
        assert any("auth-related paths" in r for r in result.reasons)

    def test_invoke_when_focus_areas_present(self):
        plan = ReviewPlan(focus_areas=["authentication", "secrets"])
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is True
        assert any("focus areas" in r for r in result.reasons)

    def test_invoke_when_memory_categories_present(self):
        plan = ReviewPlan(relevant_memory_categories=["authentication"])
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is True
        assert any("memory categories" in r for r in result.reasons)

    def test_invoke_when_bundle_has_high_focus_items(self):
        plan = ReviewPlan()
        bundle = ReviewBundle(
            items=[ReviewBundleItem(path="auth.py", review_reason="sensitive_path")]
        )
        result = evaluate_provider_gate(plan, bundle)
        assert result.should_invoke is True
        assert any("elevated review focus" in r for r in result.reasons)

    def test_invoke_with_multiple_signals(self):
        plan = ReviewPlan(
            sensitive_paths_touched=["settings.py"],
            auth_paths_touched=["auth.py"],
            focus_areas=["authentication"],
            relevant_memory_categories=["secrets"],
        )
        bundle = ReviewBundle(
            items=[ReviewBundleItem(path="auth.py", review_reason="auth_area")]
        )
        result = evaluate_provider_gate(plan, bundle)
        assert result.should_invoke is True
        assert len(result.reasons) >= 4

    def test_invoke_with_real_plan_from_sensitive_files(self):
        """End-to-end: build plan from context with auth paths."""
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is True


# ======================================================================
# evaluate_provider_gate — skip cases
# ======================================================================


class TestGateSkipCases:
    """Tests that provider invocation is skipped for weak/trivial context."""

    def test_skip_when_no_plan(self):
        result = evaluate_provider_gate(None, None)
        assert result.should_invoke is False
        assert any("no review plan" in r for r in result.reasons)

    def test_skip_when_plan_is_empty(self):
        plan = ReviewPlan()
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is False

    def test_skip_when_trivial_bundle_only(self):
        plan = ReviewPlan()
        bundle = ReviewBundle(
            items=[ReviewBundleItem(path="app.py", review_reason="changed_file")]
        )
        result = evaluate_provider_gate(plan, bundle)
        assert result.should_invoke is False
        assert any("low-focus" in r for r in result.reasons)

    def test_skip_with_real_plan_from_trivial_files(self):
        """End-to-end: build plan from trivial context — should skip."""
        ctx = _weak_ctx()
        plan = build_review_plan(ctx)
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is False

    def test_skip_reasons_are_stable_strings(self):
        plan = ReviewPlan()
        bundle = ReviewBundle(
            items=[ReviewBundleItem(path="app.py", review_reason="changed_file")]
        )
        result = evaluate_provider_gate(plan, bundle)
        for reason in result.reasons:
            assert isinstance(reason, str)
            assert len(reason) > 0
            assert reason.startswith("skip:")


# ======================================================================
# Gating reasons quality
# ======================================================================


class TestGateReasons:
    """Tests that gating reasons are stable, explainable, and well-formed."""

    def test_invoke_reasons_start_with_invoke(self):
        plan = ReviewPlan(sensitive_paths_touched=["settings.py"])
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is True
        for reason in result.reasons:
            assert reason.startswith("invoke:") or reason.startswith("skip:")

    def test_skip_reasons_start_with_skip(self):
        plan = ReviewPlan()
        result = evaluate_provider_gate(plan, None)
        assert result.should_invoke is False
        for reason in result.reasons:
            assert reason.startswith("skip:")

    def test_reasons_always_populated(self):
        # Invoke case
        plan_invoke = ReviewPlan(auth_paths_touched=["auth.py"])
        result_invoke = evaluate_provider_gate(plan_invoke, None)
        assert len(result_invoke.reasons) > 0

        # Skip case
        plan_skip = ReviewPlan()
        result_skip = evaluate_provider_gate(plan_skip, None)
        assert len(result_skip.reasons) > 0

    def test_no_plan_reason_is_descriptive(self):
        result = evaluate_provider_gate(None, None)
        assert "legacy path" in result.reasons[0]


# ======================================================================
# Disabled provider behavior unchanged
# ======================================================================


class TestDisabledProviderUnchanged:
    """Verify that DisabledProvider behavior is not affected by gating."""

    def test_disabled_provider_not_gated(self):
        """DisabledProvider is_available() returns False, gate never runs."""
        ctx = _rich_ctx()
        result = analyse(ctx, provider=DisabledProvider())
        assert isinstance(result, AnalysisResult)
        # No provider notes from disabled provider
        assert result.provider_notes == []

    def test_disabled_provider_same_as_no_provider(self):
        ctx = _rich_ctx()
        result_none = analyse(ctx)
        result_disabled = analyse(ctx, provider=DisabledProvider())
        assert len(result_none.findings) == len(result_disabled.findings)

    def test_disabled_provider_reasoning_result_has_no_gate(self):
        """When provider is disabled, gate doesn't run."""
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=DisabledProvider())
        # DisabledProvider.is_available() is False, so gate is never evaluated
        assert result.provider_gate_result is None

    def test_no_provider_reasoning_result_has_no_gate(self):
        """When no provider is provided, gate doesn't run."""
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.provider_gate_result is None


# ======================================================================
# No scoring or contract changes
# ======================================================================


class TestNoScoringChanges:
    """Verify that gating does not affect scoring or the JSON contract."""

    def test_gated_provider_does_not_affect_scoring(self):
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        result_default = analyse(ctx)
        result_mock = analyse(ctx, provider=MockProvider())
        _, score_default = derive_decision_and_risk(result_default.findings)
        _, score_mock = derive_decision_and_risk(result_mock.findings)
        assert score_default == score_mock

    def test_scan_result_unchanged_with_gating(self):
        ctx = _rich_ctx()
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
        data = json.loads(scan.model_dump_json())
        assert "scan_id" in data
        assert "findings" in data
        assert "decision" in data
        assert "risk_score" in data
        # No gating-specific keys in contract
        assert "provider_gate_result" not in data
        assert "gate_result" not in data

    def test_scan_result_unchanged_when_gated_out(self):
        ctx = _weak_ctx()
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
        data = json.loads(scan.model_dump_json())
        assert "findings" in data
        assert "provider_gate_result" not in data


# ======================================================================
# Pipeline stability — invoke path
# ======================================================================


class TestPipelineInvokePath:
    """Verify pipeline stability when provider is invoked (gate passes)."""

    def test_provider_invoked_with_rich_context(self):
        ctx = _rich_ctx()
        result = analyse(ctx, provider=MockProvider())
        mock_notes = [n for n in result.reasoning_notes if "[mock-reasoning]" in n]
        assert len(mock_notes) > 0

    def test_provider_notes_present_when_invoked(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.provider_name == "mock"
        assert result.provider_gate_result is not None
        assert result.provider_gate_result.should_invoke is True

    def test_observations_refined_when_provider_invoked(self):
        """Observations should still be refined when provider runs."""
        ctx = _rich_ctx()
        result = analyse(ctx, provider=MockProvider())
        # Pipeline should produce observations from the bundle
        assert isinstance(result.observations, list)

    def test_concerns_generated_when_provider_invoked(self):
        ctx = _rich_ctx()
        result = analyse(ctx, provider=MockProvider())
        assert isinstance(result.concerns, list)


# ======================================================================
# Pipeline stability — skip path
# ======================================================================


class TestPipelineSkipPath:
    """Verify pipeline stability when provider is skipped (gate rejects)."""

    def test_provider_skipped_with_weak_context(self):
        ctx = _weak_ctx()
        result = analyse(ctx, provider=MockProvider())
        mock_notes = [n for n in result.reasoning_notes if "[mock-reasoning]" in n]
        assert len(mock_notes) == 0

    def test_provider_name_empty_when_skipped(self):
        ctx = _weak_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.provider_name == ""

    def test_gate_result_recorded_when_skipped(self):
        ctx = _weak_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.provider_gate_result is not None
        assert result.provider_gate_result.should_invoke is False
        assert len(result.provider_gate_result.reasons) > 0

    def test_no_provider_notes_when_skipped(self):
        ctx = _weak_ctx()
        result = analyse(ctx, provider=MockProvider())
        assert result.provider_notes == []

    def test_deterministic_findings_unchanged_when_skipped(self):
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        result_no_provider = analyse(ctx)
        result_skipped = analyse(ctx, provider=MockProvider())
        assert len(result_no_provider.findings) == len(result_skipped.findings)

    def test_plan_notes_still_generated_when_skipped(self):
        """Non-provider notes should still be present."""
        ctx = _weak_ctx()
        result = analyse(ctx, provider=MockProvider())
        assert isinstance(result.reasoning_notes, list)
        assert len(result.reasoning_notes) > 0
        assert "Contextual review examined" in result.reasoning_notes[0]

    def test_bundle_still_built_when_skipped(self):
        ctx = _weak_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.bundle is not None

    def test_reasoning_request_still_assembled_when_skipped(self):
        ctx = _weak_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.reasoning_request is not None


# ======================================================================
# Gate integration with run_reasoning
# ======================================================================


class TestGateReasoningIntegration:
    """Verify gate integrates correctly with the reasoning pipeline."""

    def test_gate_result_is_none_without_plan(self):
        """Legacy path: no plan, no gate."""
        ctx = _weak_ctx()
        result = run_reasoning(ctx, plan=None, provider=MockProvider())
        assert result.provider_gate_result is None

    def test_gate_result_is_none_without_provider(self):
        """No provider: no gate evaluation."""
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=None)
        assert result.provider_gate_result is None

    def test_gate_result_recorded_on_invoke(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.provider_gate_result is not None
        assert result.provider_gate_result.should_invoke is True
        assert result.provider_name == "mock"

    def test_gate_result_recorded_on_skip(self):
        ctx = _weak_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert result.provider_gate_result is not None
        assert result.provider_gate_result.should_invoke is False
        assert result.provider_name == ""

    def test_mock_provider_not_called_when_gated_out(self):
        """Verify provider.reason() is not called when gate rejects."""
        from unittest.mock import MagicMock
        mock_provider = MagicMock(spec=MockProvider)
        mock_provider.is_available.return_value = True
        mock_provider.name = "mock"

        ctx = _weak_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=mock_provider)

        mock_provider.reason.assert_not_called()
        assert result.provider_gate_result is not None
        assert result.provider_gate_result.should_invoke is False

    def test_mock_provider_called_when_gate_passes(self):
        """Verify provider.reason() IS called when gate passes."""
        from unittest.mock import MagicMock
        from reviewer.providers import ReasoningResponse

        mock_provider = MagicMock(spec=MockProvider)
        mock_provider.is_available.return_value = True
        mock_provider.name = "mock"
        mock_provider.reason.return_value = ReasoningResponse(
            candidate_notes=["test note"],
            structured_notes=[],
            provider_name="mock",
        )

        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=mock_provider)

        mock_provider.reason.assert_called_once()
        assert result.provider_gate_result is not None
        assert result.provider_gate_result.should_invoke is True
