"""Tests for the internal ReviewTrace traceability mechanism (ADR-030).

Covers:
1. Trace generation in normal reviewer flow
2. Provider gate decision visibility
3. Disabled provider visibility
4. Provider invocation visibility
5. Suppression/refinement visibility
6. Confirmation that no trace data leaks into ScanResult JSON contract
"""

from __future__ import annotations

import json

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.models import (
    PRContent,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewPlan,
    ReviewTrace,
)
from reviewer.planner import build_review_plan
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
            repo="test/repo",
            frameworks=frameworks or [],
            auth_patterns=auth_patterns or [],
            sensitive_paths=["config/", "secrets/"],
        )
    memory = None
    if memory_entries:
        memory = ReviewMemory(
            repo="test/repo",
            entries=[
                ReviewMemoryEntry(category=cat, summary=summary)
                for cat, summary in memory_entries
            ],
        )
    return PullRequestContext(
        pr_content=pr_content,
        baseline_profile=profile,
        memory=memory,
    )


def _rich_ctx() -> PullRequestContext:
    """Create a context rich enough to trigger provider invocation."""
    return _make_ctx(
        files={
            "config/settings.py": "DEBUG = True\nSECRET_KEY = 'test'",
            "auth/login.py": "def login(user, password): pass",
        },
        frameworks=["fastapi"],
        auth_patterns=["jwt"],
        memory_entries=[("authentication", "prior auth issue found")],
    )


def _plain_ctx() -> PullRequestContext:
    """Create a plain context unlikely to trigger provider invocation."""
    return _make_ctx(files={"readme.txt": "# Hello"})


# ======================================================================
# 1. Trace generation in normal reviewer flow
# ======================================================================


class TestTraceGeneration:
    """Verify that ReviewTrace is populated during normal flow."""

    def test_trace_present_in_reasoning_result(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert isinstance(result.trace, ReviewTrace)

    def test_trace_present_in_analysis_result(self):
        ctx = _rich_ctx()
        analysis = analyse(ctx)
        assert isinstance(analysis.trace, ReviewTrace)

    def test_trace_has_focus_areas_from_plan(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.trace.active_focus_areas
        for area in result.trace.active_focus_areas:
            assert area in plan.focus_areas

    def test_trace_has_bundle_stats(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.trace.bundle_item_count > 0

    def test_trace_has_concern_count(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.trace.concern_count >= 0

    def test_trace_has_observation_count(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert result.trace.observation_count >= 0

    def test_trace_entries_not_empty(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert len(result.trace.entries) > 0

    def test_trace_entries_describe_plan_path(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        joined = " ".join(result.trace.entries)
        assert "plan" in joined.lower()

    def test_trace_on_empty_files(self):
        ctx = PullRequestContext(pr_content=PRContent.from_dict({}))
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)
        assert isinstance(result.trace, ReviewTrace)
        assert any("no changed files" in e for e in result.trace.entries)

    def test_trace_legacy_path(self):
        ctx = _rich_ctx()
        result = run_reasoning(ctx, plan=None)
        assert isinstance(result.trace, ReviewTrace)
        assert any("legacy" in e for e in result.trace.entries)


# ======================================================================
# 2. Provider gate decision visibility
# ======================================================================


class TestProviderGateDecisionVisibility:
    """Verify the trace captures provider gate decisions."""

    def test_gate_skipped_for_plain_context(self):
        ctx = _plain_ctx()
        plan = ReviewPlan()
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        assert result.trace.provider_gate_decision == "skipped"
        assert not result.trace.provider_attempted

    def test_gate_invoked_for_rich_context(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        assert result.trace.provider_gate_decision == "invoked"
        assert result.trace.provider_attempted

    def test_gate_reasons_populated_on_skip(self):
        ctx = _plain_ctx()
        plan = ReviewPlan()
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        assert len(result.trace.provider_gate_reasons) > 0

    def test_gate_reasons_populated_on_invoke(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        assert len(result.trace.provider_gate_reasons) > 0


# ======================================================================
# 3. Disabled provider visibility
# ======================================================================


class TestDisabledProviderVisibility:
    """Verify the trace captures disabled provider behaviour."""

    def test_no_provider_shows_disabled(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=None)
        assert result.trace.provider_gate_decision == "disabled"
        assert not result.trace.provider_attempted

    def test_disabled_provider_shows_unavailable(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = DisabledProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        assert result.trace.provider_gate_decision == "unavailable"
        assert not result.trace.provider_attempted

    def test_disabled_entries_mention_provider(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=None)
        joined = " ".join(result.trace.entries)
        assert "disabled" in joined.lower() or "provider" in joined.lower()

    def test_no_provider_name_when_disabled(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=None)
        assert result.trace.provider_name == ""


# ======================================================================
# 4. Provider invocation visibility
# ======================================================================


class TestProviderInvocationVisibility:
    """Verify the trace captures provider invocation details."""

    def test_provider_name_captured(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        if result.trace.provider_attempted:
            assert result.trace.provider_name != ""

    def test_provider_notes_returned_counted(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        if result.trace.provider_attempted:
            assert result.trace.provider_notes_returned >= 0

    def test_provider_notes_kept_not_exceeding_returned(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        if result.trace.provider_attempted:
            assert result.trace.provider_notes_kept <= result.trace.provider_notes_returned

    def test_entries_mention_provider_invocation(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        if result.trace.provider_attempted:
            joined = " ".join(result.trace.entries)
            assert "invoked" in joined.lower() or "provider" in joined.lower()


# ======================================================================
# 5. Suppression/refinement visibility
# ======================================================================


class TestSuppressionRefinementVisibility:
    """Verify the trace captures note suppression and observation refinement."""

    def test_suppression_count_consistent(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        if result.trace.provider_attempted:
            assert (
                result.trace.provider_notes_kept
                + result.trace.provider_notes_suppressed
                == result.trace.provider_notes_returned
            )

    def test_observation_refinement_flag(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        if result.trace.provider_attempted:
            assert result.trace.observation_refinement_applied is True

    def test_no_refinement_without_provider(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=None)
        assert result.trace.observation_refinement_applied is False

    def test_observation_count_updated_after_refinement(self):
        ctx = _rich_ctx()
        plan = build_review_plan(ctx)
        provider = MockProvider()
        result = run_reasoning(ctx, plan=plan, provider=provider)
        if result.trace.provider_attempted:
            assert result.trace.observation_count >= 0


# ======================================================================
# 6. No trace leak into ScanResult JSON contract
# ======================================================================


class TestTraceDoesNotLeakIntoContract:
    """Confirm ReviewTrace does not appear in ScanResult JSON output."""

    def test_trace_not_in_scan_result_json(self):
        ctx = _rich_ctx()
        analysis = analyse(ctx)
        decision, risk_score = derive_decision_and_risk(analysis.findings)
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
            decision=decision,
            risk_score=risk_score,
            findings=analysis.findings,
        )
        json_str = result.model_dump_json()
        data = json.loads(json_str)
        assert "trace" not in data
        assert "review_trace" not in data

    def test_trace_not_in_scan_result_keys(self):
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
        )
        data = result.model_dump()
        all_keys = set(data.keys())
        assert "trace" not in all_keys
        assert "review_trace" not in all_keys
        assert "provider_gate_decision" not in all_keys
        assert "provider_attempted" not in all_keys

    def test_scan_result_json_shape_unchanged(self):
        """ScanResult JSON keys must match the known stable set."""
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
        )
        data = result.model_dump()
        expected_keys = {
            "scan_id", "repo", "pr_number", "commit_sha", "ref",
            "timestamp", "decision", "risk_score", "findings",
        }
        assert set(data.keys()) == expected_keys

    def test_trace_accessible_from_analysis_result(self):
        ctx = _rich_ctx()
        analysis = analyse(ctx)
        assert isinstance(analysis.trace, ReviewTrace)
        assert analysis.trace.entries

    def test_trace_not_serialised_to_action_output(self):
        """Simulate the action.py flow and verify trace is absent from JSON."""
        ctx = _rich_ctx()
        analysis = analyse(ctx)
        decision, risk_score = derive_decision_and_risk(analysis.findings)
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
            decision=decision,
            risk_score=risk_score,
            findings=analysis.findings,
        )
        json_output = result.model_dump_json(indent=2)
        assert "trace" not in json_output.lower().split('"')
        parsed = json.loads(json_output)
        for key in parsed:
            assert "trace" not in key


# ======================================================================
# 7. ReviewTrace model unit tests
# ======================================================================


class TestReviewTraceModel:
    """Direct tests for the ReviewTrace dataclass."""

    def test_default_values(self):
        trace = ReviewTrace()
        assert trace.provider_attempted is False
        assert trace.provider_gate_decision == ""
        assert trace.provider_gate_reasons == []
        assert trace.provider_name == ""
        assert trace.active_focus_areas == []
        assert trace.bundle_item_count == 0
        assert trace.bundle_high_focus_count == 0
        assert trace.concern_count == 0
        assert trace.observation_count == 0
        assert trace.provider_notes_returned == 0
        assert trace.provider_notes_suppressed == 0
        assert trace.provider_notes_kept == 0
        assert trace.observation_refinement_applied is False
        assert trace.entries == []

    def test_mutable_fields_independent(self):
        t1 = ReviewTrace()
        t2 = ReviewTrace()
        t1.entries.append("entry1")
        assert t2.entries == []
        t1.active_focus_areas.append("auth")
        assert t2.active_focus_areas == []


# ======================================================================
# 8. Engine-level integration
# ======================================================================


class TestEngineTraceIntegration:
    """Verify trace flows through the engine correctly."""

    def test_analyse_returns_trace(self):
        ctx = _rich_ctx()
        analysis = analyse(ctx)
        assert isinstance(analysis.trace, ReviewTrace)
        assert analysis.trace.bundle_item_count > 0

    def test_analyse_with_provider_returns_trace(self):
        ctx = _rich_ctx()
        provider = MockProvider()
        analysis = analyse(ctx, provider=provider)
        assert isinstance(analysis.trace, ReviewTrace)

    def test_analyse_with_disabled_provider_returns_trace(self):
        ctx = _rich_ctx()
        provider = DisabledProvider()
        analysis = analyse(ctx, provider=provider)
        assert isinstance(analysis.trace, ReviewTrace)
        assert analysis.trace.provider_gate_decision == "unavailable"

    def test_mock_run_trace_not_in_json_output(self):
        """mock_run() produces ScanResult JSON that has no trace."""
        from reviewer.action import mock_run
        output = mock_run()
        json_data = json.loads(output["json"])
        assert "trace" not in json_data
