"""Tests for plan-informed review concerns (ADR-022).

Validates:
  1. Concern generation from ReviewPlan
  2. Concern relevance when sensitive/auth/memory context is present
  3. Absence of noisy concerns when context is weak or unrelated
  4. Markdown output clearly separating findings vs concerns
  5. No-overclaiming: concerns do not affect scoring or get treated as findings
"""

from __future__ import annotations

import pytest

from reviewer.models import (
    PRContent,
    PRFile,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewConcern,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewPlan,
)
from reviewer.planner import build_review_plan, generate_concerns
from reviewer.reasoning import ReasoningResult, run_reasoning
from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from schemas.findings import (
    Category,
    Confidence,
    Decision,
    Finding,
    ScanResult,
    Severity,
)


# ======================================================================
# Helpers
# ======================================================================


def _ctx(
    paths: list[str],
    baseline: RepoSecurityProfile | None = None,
    memory: ReviewMemory | None = None,
) -> PullRequestContext:
    """Build a PullRequestContext with the given file paths."""
    files = [PRFile(path=p, content="# stub") for p in paths]
    return PullRequestContext(
        pr_content=PRContent(files=files),
        baseline_profile=baseline,
        memory=memory,
    )


def _baseline(
    sensitive_paths: list[str] | None = None,
    auth_patterns: list[str] | None = None,
    frameworks: list[str] | None = None,
) -> RepoSecurityProfile:
    return RepoSecurityProfile(
        repo="test/repo",
        sensitive_paths=sensitive_paths or [],
        auth_patterns=auth_patterns or [],
        frameworks=frameworks or [],
    )


def _memory(entries: list[tuple[str, str]]) -> ReviewMemory:
    return ReviewMemory(
        repo="test/repo",
        entries=[
            ReviewMemoryEntry(category=cat, summary=summary)
            for cat, summary in entries
        ],
    )


def _make_finding(**overrides) -> Finding:
    defaults = {
        "category": Category.INSECURE_CONFIGURATION,
        "severity": Severity.MEDIUM,
        "confidence": Confidence.HIGH,
        "title": "Test finding",
        "description": "Test description",
        "file": "test.py",
    }
    defaults.update(overrides)
    return Finding(**defaults)


def _make_scan_result(findings=None, **overrides) -> ScanResult:
    defaults = {
        "repo": "test/repo",
        "pr_number": 1,
        "commit_sha": "abc1234",
        "ref": "main",
        "findings": findings or [],
    }
    defaults.update(overrides)
    return ScanResult(**defaults)


# ======================================================================
# ReviewConcern model tests
# ======================================================================


class TestReviewConcernModel:
    """Validate the ReviewConcern dataclass shape and defaults."""

    def test_default_concern(self):
        c = ReviewConcern()
        assert c.category == ""
        assert c.title == ""
        assert c.summary == ""
        assert c.confidence == "low"
        assert c.basis == ""
        assert c.related_paths == []

    def test_concern_with_fields(self):
        c = ReviewConcern(
            category="authentication",
            title="Auth area modified",
            summary="PR touches auth paths",
            confidence="medium",
            basis="auth_area",
            related_paths=["src/auth/login.py"],
        )
        assert c.category == "authentication"
        assert c.title == "Auth area modified"
        assert c.confidence == "medium"
        assert c.basis == "auth_area"
        assert "src/auth/login.py" in c.related_paths

    def test_concern_is_not_finding(self):
        """ReviewConcern must be structurally distinct from Finding."""
        concern = ReviewConcern(category="authentication", title="test")
        assert not isinstance(concern, Finding)
        assert not hasattr(concern, "severity")
        assert not hasattr(concern, "id")


# ======================================================================
# Concern generation from ReviewPlan
# ======================================================================


class TestConcernGeneration:
    """Test generate_concerns() produces concerns from ReviewPlan signals."""

    def test_auth_plus_sensitive_generates_concern(self):
        """Auth paths + sensitive paths → auth-sensitive concern."""
        ctx = _ctx(
            ["src/auth/login.py", "config/settings.py"],
            baseline=_baseline(sensitive_paths=["config/settings.py"]),
        )
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        assert len(concerns) >= 1
        auth_concern = [c for c in concerns if "Auth-sensitive" in c.title]
        assert len(auth_concern) == 1
        assert auth_concern[0].category == "authentication"
        assert auth_concern[0].confidence in ("medium", "low")
        assert auth_concern[0].basis == "sensitive_path_overlap+auth_area"

    def test_auth_pattern_plus_auth_path_generates_consistency_concern(self):
        """Baseline auth patterns + auth paths → consistency concern."""
        ctx = _ctx(
            ["src/auth/handler.py"],
            baseline=_baseline(auth_patterns=["JWT", "OAuth"]),
        )
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        consistency = [c for c in concerns if "consistency" in c.title.lower()]
        assert len(consistency) == 1
        assert "JWT" in consistency[0].summary
        assert consistency[0].basis == "baseline_auth_pattern+auth_path"

    def test_standalone_auth_path_generates_concern(self):
        """Auth paths without sensitive overlap → standalone auth concern."""
        ctx = _ctx(["src/login/handler.py"])
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        auth = [c for c in concerns if c.category == "authorization"]
        assert len(auth) >= 1
        assert any("access control" in c.summary.lower() for c in auth)

    def test_standalone_sensitive_path_generates_concern(self):
        """Sensitive paths without auth overlap → config concern."""
        ctx = _ctx(["deploy/production.yml"])
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        config = [c for c in concerns if c.category == "insecure_configuration"]
        assert len(config) >= 1
        assert any("sensitive" in c.summary.lower() for c in config)

    def test_memory_match_generates_concern(self):
        """Memory categories matching PR paths → memory concern."""
        mem = _memory([
            ("authentication", "Prior auth boundary issue found"),
            ("authorization", "Role check was missing in admin routes"),
        ])
        ctx = _ctx(["src/auth/middleware.py"], memory=mem)
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        memory_concerns = [c for c in concerns if c.basis == "memory_match"]
        assert len(memory_concerns) == 1
        assert "prior" in memory_concerns[0].summary.lower()

    def test_framework_plus_sensitive_generates_concern(self):
        """Framework context + sensitive paths → framework concern."""
        ctx = _ctx(
            ["config/app_settings.py"],
            baseline=_baseline(
                frameworks=["Django"],
                sensitive_paths=["config/app_settings.py"],
            ),
        )
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        framework = [c for c in concerns if "framework" in c.title.lower()]
        assert len(framework) == 1
        assert "Django" in framework[0].summary


# ======================================================================
# Absence of noisy concerns
# ======================================================================


class TestNoConcernNoise:
    """Concerns should NOT be generated when context is weak or unrelated."""

    def test_no_concerns_for_plain_files(self):
        """No sensitive/auth/memory context → no concerns."""
        ctx = _ctx(["src/utils.py", "src/helpers.py"])
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)
        assert concerns == []

    def test_no_concerns_for_empty_pr(self):
        """Empty PR → empty plan → no concerns."""
        ctx = _ctx([])
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)
        assert concerns == []

    def test_no_concerns_for_irrelevant_memory(self):
        """Memory that doesn't match PR paths → no memory concern."""
        mem = _memory([("dependency_risk", "Outdated package found")])
        ctx = _ctx(["src/utils.py"], memory=mem)
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        memory_concerns = [c for c in concerns if c.basis == "memory_match"]
        assert len(memory_concerns) == 0

    def test_no_framework_concern_without_sensitive_paths(self):
        """Framework context alone (no sensitive paths) → no framework concern."""
        ctx = _ctx(
            ["src/utils.py"],
            baseline=_baseline(frameworks=["Flask"]),
        )
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        framework = [c for c in concerns if "framework" in c.title.lower()]
        assert len(framework) == 0

    def test_concerns_bounded_no_duplicates(self):
        """No duplicate concerns for the same area."""
        ctx = _ctx(
            ["src/auth/login.py", "src/auth/logout.py"],
            baseline=_baseline(
                sensitive_paths=["src/auth/login.py"],
                auth_patterns=["JWT"],
                frameworks=["FastAPI"],
            ),
        )
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        titles = [c.title for c in concerns]
        # No duplicate titles
        assert len(titles) == len(set(titles))


# ======================================================================
# Concerns in reasoning result
# ======================================================================


class TestConcernsInReasoningResult:
    """Concerns flow through run_reasoning when a plan is provided."""

    def test_reasoning_result_has_concerns_field(self):
        result = ReasoningResult()
        assert hasattr(result, "concerns")
        assert result.concerns == []

    def test_run_reasoning_with_plan_produces_concerns(self):
        ctx = _ctx(
            ["src/auth/login.py", "config/settings.py"],
            baseline=_baseline(sensitive_paths=["config/settings.py"]),
        )
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan)

        assert isinstance(result.concerns, list)
        assert len(result.concerns) >= 1
        assert all(isinstance(c, ReviewConcern) for c in result.concerns)

    def test_run_reasoning_without_plan_no_concerns(self):
        """Legacy path (no plan) → no concerns generated."""
        ctx = _ctx(
            ["src/auth/login.py"],
            baseline=_baseline(sensitive_paths=["src/auth/login.py"]),
        )
        result = run_reasoning(ctx, plan=None)
        assert result.concerns == []


# ======================================================================
# Concerns in engine AnalysisResult
# ======================================================================


class TestConcernsInEngine:
    """Concerns flow through the engine analyse() function."""

    def test_analysis_result_has_concerns(self):
        result = AnalysisResult()
        assert hasattr(result, "concerns")
        assert result.concerns == []

    def test_analyse_produces_concerns_for_sensitive_pr(self):
        ctx = _ctx(
            ["src/auth/handler.py", "config/database.py"],
            baseline=_baseline(
                sensitive_paths=["config/database.py"],
                auth_patterns=["JWT"],
            ),
        )
        result = analyse(ctx)

        assert isinstance(result.concerns, list)
        assert len(result.concerns) >= 1

    def test_analyse_no_concerns_for_plain_pr(self):
        ctx = _ctx(["src/utils.py", "src/helpers.py"])
        result = analyse(ctx)
        assert result.concerns == []


# ======================================================================
# Markdown output separation
# ======================================================================


class TestMarkdownConcernOutput:
    """Markdown output clearly separates findings from concerns."""

    def test_concerns_section_present(self):
        result = _make_scan_result()
        concerns = [ReviewConcern(
            category="authentication",
            title="Auth area modified",
            summary="PR touches auth paths",
            confidence="medium",
            basis="auth_area",
            related_paths=["src/auth/login.py"],
        )]
        md = format_markdown(result, concerns=concerns)

        assert "Review Concerns" in md
        assert "Auth area modified" in md
        assert "PR touches auth paths" in md
        assert "not proven findings" in md.lower()

    def test_concerns_not_in_findings_section(self):
        finding = _make_finding(title="Real Finding")
        result = _make_scan_result(findings=[finding])
        concerns = [ReviewConcern(
            category="authentication",
            title="Concern Title",
            summary="Concern summary",
        )]
        md = format_markdown(result, concerns=concerns)

        # Both sections present
        assert "Real Finding" in md
        assert "Concern Title" in md
        assert "Review Concerns" in md

        # Concern appears after findings section
        finding_pos = md.index("Real Finding")
        concern_pos = md.index("Concern Title")
        assert concern_pos > finding_pos

    def test_no_concerns_section_when_empty(self):
        result = _make_scan_result()
        md = format_markdown(result, concerns=[])
        assert "Review Concerns" not in md

    def test_no_concerns_section_when_none(self):
        result = _make_scan_result()
        md = format_markdown(result, concerns=None)
        assert "Review Concerns" not in md

    def test_backward_compat_no_concerns_arg(self):
        result = _make_scan_result()
        md = format_markdown(result)
        assert "Review Concerns" not in md

    def test_concern_shows_confidence(self):
        concerns = [ReviewConcern(
            category="secrets",
            title="Secret area",
            summary="test",
            confidence="low",
        )]
        md = format_markdown(_make_scan_result(), concerns=concerns)
        assert "confidence: low" in md

    def test_concern_shows_related_paths(self):
        concerns = [ReviewConcern(
            category="authentication",
            title="Test concern",
            summary="test",
            related_paths=["src/auth/login.py", "src/auth/logout.py"],
        )]
        md = format_markdown(_make_scan_result(), concerns=concerns)
        assert "`src/auth/login.py`" in md

    def test_disclaimer_text_present(self):
        """The concerns section includes a disclaimer about uncertainty."""
        concerns = [ReviewConcern(
            category="authentication",
            title="Test",
            summary="test",
        )]
        md = format_markdown(_make_scan_result(), concerns=concerns)
        assert "not proven findings" in md.lower()


# ======================================================================
# No-overclaiming: concerns do not affect scoring
# ======================================================================


class TestNoOverclaiming:
    """Concerns must not inflate findings, scoring, or decisions."""

    def test_concerns_do_not_produce_findings(self):
        """Even with strong context, concerns are separate from findings."""
        ctx = _ctx(
            ["src/auth/login.py", "config/secrets.py"],
            baseline=_baseline(
                sensitive_paths=["config/secrets.py"],
                auth_patterns=["JWT", "OAuth"],
                frameworks=["Django"],
            ),
            memory=_memory([
                ("authentication", "Auth bypass found previously"),
            ]),
        )
        result = analyse(ctx)

        # Concerns should exist
        assert len(result.concerns) >= 1

        # But no findings from concerns — only deterministic findings
        for f in result.findings:
            assert isinstance(f, Finding)
        # Concerns are not findings
        for c in result.concerns:
            assert isinstance(c, ReviewConcern)
            assert not isinstance(c, Finding)

    def test_concerns_do_not_affect_risk_score(self):
        """Risk score comes only from findings, not concerns."""
        # PR with concerns but no deterministic check triggers
        ctx = _ctx(
            ["src/auth/login.py"],
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        result = analyse(ctx)

        assert len(result.concerns) >= 1
        decision, risk_score = derive_decision_and_risk(result.findings)
        # No deterministic findings → score should be 0
        if not result.findings:
            assert risk_score == 0
            assert decision == Decision.PASS

    def test_concerns_do_not_change_decision(self):
        """Decision is derived from findings only, not concerns."""
        ctx = _ctx(
            ["src/auth/login.py", "config/settings.py"],
            baseline=_baseline(
                sensitive_paths=["config/settings.py"],
                auth_patterns=["JWT"],
            ),
        )
        result = analyse(ctx)

        assert len(result.concerns) >= 1
        decision, _ = derive_decision_and_risk(result.findings)
        # Decision based only on findings, not concerns
        assert decision in (Decision.PASS, Decision.WARN)

    def test_concern_confidence_is_honest(self):
        """Concerns should have low or medium confidence, never high."""
        ctx = _ctx(
            ["src/auth/login.py", "config/settings.py"],
            baseline=_baseline(
                sensitive_paths=["config/settings.py"],
                auth_patterns=["JWT"],
                frameworks=["Django"],
            ),
            memory=_memory([("authentication", "Prior issue")]),
        )
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        for c in concerns:
            assert c.confidence in ("low", "medium"), (
                f"Concern '{c.title}' has confidence '{c.confidence}' — "
                f"concerns should not overclaim with high confidence"
            )

    def test_concern_summary_does_not_claim_vulnerability(self):
        """Concern summaries should not use vulnerability language."""
        ctx = _ctx(
            ["src/auth/login.py"],
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)

        vulnerability_words = ["vulnerability", "exploit", "attack", "breach", "compromised"]
        for c in concerns:
            summary_lower = c.summary.lower()
            for word in vulnerability_words:
                assert word not in summary_lower, (
                    f"Concern '{c.title}' uses vulnerability language: '{word}'"
                )


# ======================================================================
# JSON contract stability
# ======================================================================


class TestJsonContractStability:
    """ScanResult JSON contract must not include concerns."""

    def test_scan_result_json_has_no_concerns(self):
        """Concerns are not part of the ScanResult JSON contract."""
        result = _make_scan_result()
        json_data = result.model_dump()
        assert "concerns" not in json_data

    def test_scan_result_json_shape_unchanged(self):
        """ScanResult JSON shape is stable."""
        result = _make_scan_result(findings=[_make_finding()])
        json_data = result.model_dump()

        expected_keys = {
            "scan_id", "repo", "pr_number", "commit_sha", "ref",
            "timestamp", "decision", "risk_score", "findings",
        }
        assert set(json_data.keys()) == expected_keys


# ======================================================================
# Integration: full flow with concerns
# ======================================================================


class TestFullFlowWithConcerns:
    """End-to-end flow produces both findings and concerns correctly."""

    def test_mock_run_includes_concerns(self):
        from reviewer.action import mock_run
        output = mock_run()

        assert "concerns" in output
        assert isinstance(output["concerns"], list)

    def test_full_flow_sensitive_pr(self):
        """Full flow with sensitive PR produces concerns + deterministic findings."""
        ctx = _ctx(
            ["config/settings.py", "src/auth/handler.py"],
            baseline=_baseline(
                sensitive_paths=["config/settings.py"],
                auth_patterns=["JWT"],
            ),
        )
        # Inject content that triggers deterministic check
        ctx.pr_content.files[0] = PRFile(
            path="config/settings.py",
            content="DEBUG = True\nSECRET_KEY = 'changeme'\n",
        )

        result = analyse(ctx)

        # Should have deterministic findings
        assert len(result.findings) >= 1
        # Should have contextual concerns
        assert len(result.concerns) >= 1
        # Findings and concerns are distinct types
        for f in result.findings:
            assert isinstance(f, Finding)
        for c in result.concerns:
            assert isinstance(c, ReviewConcern)

        # Markdown output shows both
        decision, risk_score = derive_decision_and_risk(result.findings)
        scan = _make_scan_result(
            findings=result.findings,
            decision=decision,
            risk_score=risk_score,
        )
        md = format_markdown(scan, concerns=result.concerns)
        assert "Review Concerns" in md
        # Footer still present
        assert "Scan:" in md
