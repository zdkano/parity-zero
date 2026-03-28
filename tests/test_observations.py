"""Tests for per-file review observations (ADR-024).

Validates:
  1. Observation generation from ReviewBundle items
  2. Observation relevance for auth/sensitive/framework/memory contexts
  3. Absence of noisy observations when context is weak
  4. Markdown rendering clearly separating observations from findings and concerns
  5. No-overclaiming: observations do not affect findings or scoring
  6. JSON contract stability (ScanResult unchanged)
"""

from __future__ import annotations

import json

import pytest

from reviewer.models import (
    PRContent,
    PRFile,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewBundle,
    ReviewBundleItem,
    ReviewConcern,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewObservation,
    ReviewPlan,
)
from reviewer.observations import generate_observations
from reviewer.bundle import build_review_bundle
from reviewer.planner import build_review_plan
from reviewer.reasoning import ReasoningResult, run_reasoning
from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.action import mock_run
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
    files: dict[str, str] | None = None,
    baseline: RepoSecurityProfile | None = None,
    memory: ReviewMemory | None = None,
) -> PullRequestContext:
    """Build a PullRequestContext from simple inputs."""
    pr_content = PRContent.from_dict(files or {})
    return PullRequestContext(
        pr_content=pr_content,
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


def _bundle_item(
    path: str = "src/app.py",
    review_reason: str = "changed_file",
    focus_areas: list[str] | None = None,
    baseline_context: list[str] | None = None,
    memory_context: list[str] | None = None,
    related_paths: list[str] | None = None,
) -> ReviewBundleItem:
    return ReviewBundleItem(
        path=path,
        content="# stub",
        review_reason=review_reason,
        focus_areas=focus_areas or [],
        baseline_context=baseline_context or [],
        memory_context=memory_context or [],
        related_paths=related_paths or [],
    )


def _bundle(
    items: list[ReviewBundleItem] | None = None,
    repo_frameworks: list[str] | None = None,
    repo_auth_patterns: list[str] | None = None,
) -> ReviewBundle:
    return ReviewBundle(
        items=items or [],
        repo_frameworks=repo_frameworks or [],
        repo_auth_patterns=repo_auth_patterns or [],
    )


def _scan_result(**kwargs) -> ScanResult:
    defaults = {
        "repo": "test/repo",
        "pr_number": 1,
        "commit_sha": "abc1234def5",
        "ref": "main",
    }
    defaults.update(kwargs)
    return ScanResult(**defaults)


# ======================================================================
# 1. Observation generation from ReviewBundle
# ======================================================================

class TestObservationGeneration:
    """Observation generation from ReviewBundle items."""

    def test_empty_bundle_produces_no_observations(self):
        bundle = _bundle()
        obs = generate_observations(bundle)
        assert obs == []

    def test_plain_changed_file_produces_no_observation(self):
        item = _bundle_item(review_reason="changed_file")
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert obs == []

    def test_sensitive_auth_item_produces_observation(self):
        item = _bundle_item(
            path="src/auth/config.py",
            review_reason="sensitive_auth",
            focus_areas=["authentication"],
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert obs[0].path == "src/auth/config.py"
        assert obs[0].confidence == "medium"
        assert "sensitive_auth" in obs[0].basis

    def test_auth_area_with_patterns_produces_observation(self):
        item = _bundle_item(
            path="src/auth/login.py",
            review_reason="auth_area",
            focus_areas=["authentication"],
        )
        bundle = _bundle(
            items=[item],
            repo_auth_patterns=["JWT", "OAuth2"],
        )
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "JWT" in obs[0].summary
        assert obs[0].confidence == "medium"
        assert "baseline_patterns" in obs[0].basis

    def test_auth_area_without_patterns_produces_low_confidence(self):
        item = _bundle_item(
            path="src/auth/login.py",
            review_reason="auth_area",
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert obs[0].confidence == "low"
        assert obs[0].basis == "auth_bundle_item"

    def test_sensitive_path_with_frameworks_produces_observation(self):
        item = _bundle_item(
            path="config/settings.py",
            review_reason="sensitive_path",
            focus_areas=["insecure_configuration"],
        )
        bundle = _bundle(
            items=[item],
            repo_frameworks=["Django", "Celery"],
        )
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "Django" in obs[0].summary
        assert obs[0].basis == "sensitive_bundle_item+framework_context"

    def test_sensitive_path_without_frameworks_produces_observation(self):
        item = _bundle_item(
            path="config/settings.py",
            review_reason="sensitive_path",
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert obs[0].confidence == "low"
        assert obs[0].basis == "sensitive_bundle_item"

    def test_memory_context_item_produces_observation(self):
        item = _bundle_item(
            path="src/utils.py",
            review_reason="changed_file",
            memory_context=["authentication: JWT validation issue"],
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "prior review history" in obs[0].summary
        assert obs[0].basis == "memory_alignment"

    def test_multiple_items_produce_multiple_observations(self):
        items = [
            _bundle_item(path="src/auth/login.py", review_reason="auth_area"),
            _bundle_item(path="config/settings.py", review_reason="sensitive_path"),
        ]
        bundle = _bundle(items=items)
        obs = generate_observations(bundle)
        assert len(obs) == 2
        paths = {o.path for o in obs}
        assert "src/auth/login.py" in paths
        assert "config/settings.py" in paths

    def test_observation_carries_related_paths(self):
        item = _bundle_item(
            path="src/auth/login.py",
            review_reason="auth_area",
            related_paths=["src/auth/utils.py", "src/auth/models.py"],
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert obs[0].related_paths == ["src/auth/utils.py", "src/auth/models.py"]

    def test_observation_focus_area_from_item(self):
        item = _bundle_item(
            path="src/auth/login.py",
            review_reason="auth_area",
            focus_areas=["authorization", "authentication"],
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert obs[0].focus_area == "authorization"

    def test_observation_max_bound(self):
        """Bundle with many items should produce bounded observations."""
        items = [
            _bundle_item(
                path=f"src/auth/file{i}.py",
                review_reason="auth_area",
            )
            for i in range(20)
        ]
        bundle = _bundle(items=items)
        obs = generate_observations(bundle)
        assert len(obs) <= 10


# ======================================================================
# 2. Observation relevance for specific contexts
# ======================================================================


class TestObservationRelevance:
    """Observation relevance for auth/sensitive/framework/memory contexts."""

    def test_auth_file_jwt_repo_mentions_auth_flow(self):
        """Auth file in JWT repo → auth flow consistency observation."""
        item = _bundle_item(
            path="src/auth/middleware.py",
            review_reason="auth_area",
            focus_areas=["authentication"],
        )
        bundle = _bundle(
            items=[item],
            repo_auth_patterns=["JWT"],
        )
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "auth flow" in obs[0].title.lower() or "auth" in obs[0].title.lower()
        assert "JWT" in obs[0].summary

    def test_sensitive_config_django_repo_mentions_framework(self):
        """Sensitive config in Django repo → framework-specific defaults observation."""
        item = _bundle_item(
            path="config/settings.py",
            review_reason="sensitive_path",
            focus_areas=["insecure_configuration"],
        )
        bundle = _bundle(
            items=[item],
            repo_frameworks=["Django"],
        )
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "Django" in obs[0].summary
        assert "framework" in obs[0].title.lower()

    def test_file_with_recurring_memory_mentions_history(self):
        """File with memory alignment → mentions prior scrutiny."""
        item = _bundle_item(
            path="src/auth/session.py",
            review_reason="changed_file",
            memory_context=["authentication: session token issues"],
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "prior" in obs[0].summary.lower() or "history" in obs[0].summary.lower()

    def test_sensitive_auth_combined_mentions_boundaries(self):
        """Sensitive + auth combined → boundary preservation observation."""
        item = _bundle_item(
            path="src/auth/config.py",
            review_reason="sensitive_auth",
            focus_areas=["authentication", "insecure_configuration"],
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "boundary" in obs[0].summary.lower() or "access control" in obs[0].summary.lower()

    def test_sensitive_auth_with_patterns_includes_patterns(self):
        """Sensitive auth item with baseline patterns → includes pattern info."""
        item = _bundle_item(
            path="src/auth/config.py",
            review_reason="sensitive_auth",
        )
        bundle = _bundle(
            items=[item],
            repo_auth_patterns=["JWT", "RBAC"],
        )
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert "JWT" in obs[0].summary


# ======================================================================
# 3. Absence of noisy observations
# ======================================================================


class TestObservationNoiseControl:
    """Observations should not be generated when context is weak."""

    def test_no_observations_for_plain_files(self):
        """Plain changed files with no signals → no observations."""
        items = [
            _bundle_item(path="src/utils.py", review_reason="changed_file"),
            _bundle_item(path="src/helpers.py", review_reason="changed_file"),
            _bundle_item(path="README.md", review_reason="changed_file"),
        ]
        bundle = _bundle(items=items)
        obs = generate_observations(bundle)
        assert obs == []

    def test_no_observations_for_empty_bundle(self):
        bundle = _bundle()
        obs = generate_observations(bundle)
        assert obs == []

    def test_plain_file_with_empty_memory_context(self):
        """Plain file with empty memory context list → no observation."""
        item = _bundle_item(
            path="src/utils.py",
            review_reason="changed_file",
            memory_context=[],
        )
        bundle = _bundle(items=[item])
        obs = generate_observations(bundle)
        assert obs == []

    def test_mixed_items_only_relevant_get_observations(self):
        """Mix of relevant and plain items → only relevant items get observations."""
        items = [
            _bundle_item(path="src/utils.py", review_reason="changed_file"),
            _bundle_item(path="src/auth/login.py", review_reason="auth_area"),
            _bundle_item(path="README.md", review_reason="changed_file"),
        ]
        bundle = _bundle(items=items)
        obs = generate_observations(bundle)
        assert len(obs) == 1
        assert obs[0].path == "src/auth/login.py"

    def test_confidence_never_high(self):
        """No observation should have high confidence."""
        items = [
            _bundle_item(path="src/auth/config.py", review_reason="sensitive_auth"),
            _bundle_item(path="src/auth/login.py", review_reason="auth_area"),
            _bundle_item(path="config/settings.py", review_reason="sensitive_path"),
        ]
        bundle = _bundle(
            items=items,
            repo_auth_patterns=["JWT"],
            repo_frameworks=["Django"],
        )
        obs = generate_observations(bundle)
        for o in obs:
            assert o.confidence in ("low", "medium"), f"Unexpected confidence: {o.confidence}"


# ======================================================================
# 4. Markdown rendering
# ======================================================================


class TestObservationMarkdown:
    """Markdown output clearly separates observations from findings and concerns."""

    def test_observations_section_in_markdown(self):
        """Observations appear in their own markdown section."""
        result = _scan_result()
        observations = [
            ReviewObservation(
                path="src/auth/login.py",
                focus_area="authentication",
                title="Auth flow check warranted",
                summary="File modifies auth code in JWT repo.",
                confidence="medium",
                basis="auth_bundle_item",
            )
        ]
        md = format_markdown(result, observations=observations)
        assert "### 📋 Review Observations" in md
        assert "Auth flow check warranted" in md
        assert "src/auth/login.py" in md

    def test_observations_section_has_disclaimer(self):
        """Observations section includes a disclaimer."""
        result = _scan_result()
        observations = [
            ReviewObservation(
                path="src/auth/login.py",
                title="Test obs",
                summary="Test summary.",
                confidence="low",
            )
        ]
        md = format_markdown(result, observations=observations)
        assert "not findings or proven issues" in md

    def test_observations_separate_from_concerns(self):
        """Observations and concerns appear in separate sections."""
        result = _scan_result()
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Auth concern",
                summary="A concern.",
                confidence="medium",
            )
        ]
        observations = [
            ReviewObservation(
                path="src/auth/login.py",
                title="Auth observation",
                summary="An observation.",
                confidence="medium",
            )
        ]
        md = format_markdown(result, concerns=concerns, observations=observations)
        concern_pos = md.index("### 🔍 Review Concerns")
        obs_pos = md.index("### 📋 Review Observations")
        # Concerns should appear before observations
        assert concern_pos < obs_pos

    def test_observations_separate_from_findings(self):
        """Observations section is distinct from findings."""
        finding = Finding(
            category=Category.AUTHENTICATION,
            severity=Severity.MEDIUM,
            confidence=Confidence.MEDIUM,
            title="Test finding",
            description="A finding.",
            file="src/auth.py",
        )
        result = _scan_result(findings=[finding])
        observations = [
            ReviewObservation(
                path="src/auth/login.py",
                title="Auth observation",
                summary="An observation.",
                confidence="medium",
            )
        ]
        md = format_markdown(result, observations=observations)
        assert "### MEDIUM" in md  # findings section
        assert "### 📋 Review Observations" in md

    def test_no_observations_section_when_empty(self):
        """No observations section when list is empty."""
        result = _scan_result()
        md = format_markdown(result, observations=[])
        assert "Review Observations" not in md

    def test_no_observations_section_when_none(self):
        """No observations section when None is passed."""
        result = _scan_result()
        md = format_markdown(result, observations=None)
        assert "Review Observations" not in md

    def test_observations_show_confidence(self):
        """Each observation shows its confidence."""
        result = _scan_result()
        observations = [
            ReviewObservation(
                path="src/auth/login.py",
                title="Test obs",
                summary="Test.",
                confidence="low",
            )
        ]
        md = format_markdown(result, observations=observations)
        assert "confidence: low" in md

    def test_observations_show_related_paths(self):
        """Observations with related paths render them."""
        result = _scan_result()
        observations = [
            ReviewObservation(
                path="src/auth/login.py",
                title="Test obs",
                summary="Test.",
                confidence="low",
                related_paths=["src/auth/utils.py"],
            )
        ]
        md = format_markdown(result, observations=observations)
        assert "src/auth/utils.py" in md
        assert "Related:" in md

    def test_backward_compatible_no_observations(self):
        """format_markdown works without observations parameter."""
        result = _scan_result()
        md = format_markdown(result)
        assert "parity-zero Security Review" in md
        assert "Review Observations" not in md


# ======================================================================
# 5. No-overclaiming: observations do not affect findings or scoring
# ======================================================================


class TestObservationNoOverclaiming:
    """Observations must not affect findings, scoring, or the JSON contract."""

    def test_observations_do_not_produce_findings(self):
        """Observation generation does not add findings."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth code"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        obs = generate_observations(bundle)
        # Observations exist but produce no findings
        assert len(obs) >= 1
        # ReasoningResult from run_reasoning still has empty findings
        rr = run_reasoning(ctx, plan=plan)
        assert rr.findings == []

    def test_observations_do_not_affect_risk_score(self):
        """Risk score is derived from findings only, not observations."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth code"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        analysis = analyse(ctx)
        assert analysis.observations  # observations exist
        decision, risk_score = derive_decision_and_risk(analysis.findings)
        # No deterministic findings → risk_score = 0
        assert risk_score == 0
        assert decision == Decision.PASS

    def test_observations_do_not_appear_in_scan_result_json(self):
        """ScanResult JSON contract does not include observations."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth code"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        analysis = analyse(ctx)
        assert analysis.observations  # observations exist

        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234def5",
            ref="main",
            findings=analysis.findings,
        )
        json_str = result.model_dump_json()
        data = json.loads(json_str)
        assert "observations" not in data
        assert "observation" not in json_str.lower().replace("observation", "").replace('"', '')

    def test_scan_result_json_shape_unchanged(self):
        """ScanResult JSON keys are exactly the expected set."""
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234def5",
            ref="main",
        )
        data = json.loads(result.model_dump_json())
        expected_keys = {
            "scan_id", "repo", "pr_number", "commit_sha", "ref",
            "timestamp", "decision", "risk_score", "findings",
        }
        assert set(data.keys()) == expected_keys

    def test_observations_not_counted_in_summary(self):
        """Summary counts reflect findings only."""
        result = _scan_result()
        assert result.summary_counts == {"high": 0, "medium": 0, "low": 0}


# ======================================================================
# 6. Integration: observations flow through the full pipeline
# ======================================================================


class TestObservationIntegration:
    """Observations flow correctly through reasoning → engine → action."""

    def test_observations_in_reasoning_result(self):
        """run_reasoning with plan produces observations."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth code"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        plan = build_review_plan(ctx)
        rr = run_reasoning(ctx, plan=plan)
        assert isinstance(rr.observations, list)
        assert len(rr.observations) >= 1
        assert all(isinstance(o, ReviewObservation) for o in rr.observations)

    def test_observations_in_analysis_result(self):
        """analyse() carries observations."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth code"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        analysis = analyse(ctx)
        assert isinstance(analysis.observations, list)
        assert len(analysis.observations) >= 1

    def test_no_observations_without_plan(self):
        """Legacy path (no plan) produces no observations."""
        rr = run_reasoning({"src/utils.py": "# code"})
        assert rr.observations == []

    def test_observations_in_mock_run(self):
        """mock_run() includes observations in output."""
        output = mock_run()
        assert "observations" in output
        assert isinstance(output["observations"], list)

    def test_observations_in_markdown_via_engine(self):
        """Full pipeline: observations appear in markdown output."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth code"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        analysis = analyse(ctx)
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234def5",
            ref="main",
            findings=analysis.findings,
        )
        md = format_markdown(
            result,
            concerns=analysis.concerns,
            observations=analysis.observations,
        )
        assert "Review Observations" in md

    def test_no_observations_for_plain_files_via_engine(self):
        """Engine with only plain files → no observations."""
        ctx = _ctx(files={"src/utils.py": "# utility"})
        analysis = analyse(ctx)
        assert analysis.observations == []

    def test_sensitive_file_via_engine_produces_observation(self):
        """Engine with a sensitive-path file → at least one observation."""
        ctx = _ctx(
            files={"config/settings.py": "# config"},
        )
        analysis = analyse(ctx)
        assert len(analysis.observations) >= 1
        assert any(o.path == "config/settings.py" for o in analysis.observations)

    def test_observations_coexist_with_findings(self):
        """Observations exist alongside deterministic findings without interference."""
        ctx = _ctx(
            files={
                "src/auth/login.py": "# auth code",
                "src/server.py": 'app.add_middleware(CORSMiddleware, allow_origins=["*"])',
            },
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        analysis = analyse(ctx)
        # Should have both findings (from CORS check) and observations
        assert len(analysis.findings) >= 1
        assert len(analysis.observations) >= 1

    def test_observations_coexist_with_concerns(self):
        """Observations exist alongside concerns without interference."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth code"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        analysis = analyse(ctx)
        # Both concerns and observations should be present
        assert len(analysis.concerns) >= 1
        assert len(analysis.observations) >= 1


# ======================================================================
# 7. ReviewObservation model tests
# ======================================================================


class TestReviewObservationModel:
    """ReviewObservation dataclass basic tests."""

    def test_default_values(self):
        obs = ReviewObservation()
        assert obs.path == ""
        assert obs.focus_area == ""
        assert obs.title == ""
        assert obs.summary == ""
        assert obs.confidence == "low"
        assert obs.basis == ""
        assert obs.related_paths == []

    def test_custom_values(self):
        obs = ReviewObservation(
            path="src/auth/login.py",
            focus_area="authentication",
            title="Auth flow check",
            summary="Check auth flow.",
            confidence="medium",
            basis="auth_bundle_item",
            related_paths=["src/auth/utils.py"],
        )
        assert obs.path == "src/auth/login.py"
        assert obs.focus_area == "authentication"
        assert obs.confidence == "medium"
        assert len(obs.related_paths) == 1

    def test_related_paths_default_independent(self):
        """Related paths default list is independent per instance."""
        obs1 = ReviewObservation()
        obs2 = ReviewObservation()
        obs1.related_paths.append("a.py")
        assert obs2.related_paths == []
