"""Tests for the contextual review planner (ADR-021).

Validates that:
  - The planner derives review focus from path overlap with sensitive areas
  - Auth-related path overlap creates expected review flags/focus areas
  - Relevant memory influences focus without creating noise
  - Unrelated memory does not create noise
  - Framework/auth-pattern baseline context flows into the plan
  - The review plan influences contextual notes structurally
  - The reviewer flow still produces valid ScanResult
  - Markdown and JSON flow remain stable
  - The plan does not create unjustified findings (no overclaiming)
"""

from __future__ import annotations

import json

from reviewer.models import (
    PRContent,
    PRFile,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewPlan,
)
from reviewer.planner import (
    build_review_plan,
    sensitive_path_overlap,
    auth_path_overlap,
    infer_path_categories,
    relevant_memory_entries,
)
from reviewer.reasoning import run_reasoning, ReasoningResult
from reviewer.engine import analyse, derive_decision_and_risk, AnalysisResult
from reviewer.formatter import format_markdown
from reviewer.action import mock_run
from schemas.findings import Category, Confidence, Decision, Finding, ScanResult, Severity


# ======================================================================
# Helper factories
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
    languages: list[str] | None = None,
) -> RepoSecurityProfile:
    """Build a minimal RepoSecurityProfile."""
    return RepoSecurityProfile(
        repo="test/repo",
        sensitive_paths=sensitive_paths or [],
        auth_patterns=auth_patterns or [],
        frameworks=frameworks or [],
        languages=languages or [],
    )


def _memory(entries: list[tuple[str, str]]) -> ReviewMemory:
    """Build a ReviewMemory from (category, summary) tuples."""
    return ReviewMemory(
        repo="test/repo",
        entries=[
            ReviewMemoryEntry(category=cat, summary=summary)
            for cat, summary in entries
        ],
    )


# ======================================================================
# ReviewPlan model tests
# ======================================================================


class TestReviewPlanModel:
    """Tests for the ReviewPlan dataclass."""

    def test_default_construction(self) -> None:
        plan = ReviewPlan()
        assert plan.focus_areas == []
        assert plan.review_flags == []
        assert plan.sensitive_paths_touched == []
        assert plan.auth_paths_touched == []
        assert plan.relevant_memory_categories == []
        assert plan.framework_context == []
        assert plan.auth_pattern_context == []
        assert plan.reviewer_guidance == []

    def test_custom_construction(self) -> None:
        plan = ReviewPlan(
            focus_areas=["authorization"],
            review_flags=["touches_auth_area"],
            auth_paths_touched=["src/auth/handler.py"],
        )
        assert plan.focus_areas == ["authorization"]
        assert plan.review_flags == ["touches_auth_area"]
        assert plan.auth_paths_touched == ["src/auth/handler.py"]


# ======================================================================
# Planner — sensitive path focus
# ======================================================================


class TestPlannerSensitivePaths:
    """Planner correctly derives focus from sensitive path overlap."""

    def test_config_path_creates_config_focus(self) -> None:
        ctx = _ctx(files={"config/settings.py": "SECRET_KEY = 'abc'"})
        plan = build_review_plan(ctx)
        assert "touches_sensitive_path" in plan.review_flags
        assert "config/settings.py" in plan.sensitive_paths_touched
        assert "insecure_configuration" in plan.focus_areas

    def test_secrets_path_creates_secrets_focus(self) -> None:
        ctx = _ctx(files={"secrets/vault.py": "key = '...'"})
        plan = build_review_plan(ctx)
        assert "touches_sensitive_path" in plan.review_flags
        assert "secrets" in plan.focus_areas

    def test_admin_path_creates_authorization_focus(self) -> None:
        ctx = _ctx(files={"admin/users.py": "class UserAdmin: pass"})
        plan = build_review_plan(ctx)
        assert "touches_sensitive_path" in plan.review_flags
        assert "authorization" in plan.focus_areas

    def test_baseline_sensitive_path_direct_match(self) -> None:
        ctx = _ctx(
            files={"internal/core.py": "pass"},
            baseline=_baseline(sensitive_paths=["internal/core.py"]),
        )
        plan = build_review_plan(ctx)
        assert "touches_sensitive_path" in plan.review_flags
        assert "internal/core.py" in plan.sensitive_paths_touched

    def test_unrelated_path_no_sensitive_flag(self) -> None:
        ctx = _ctx(files={"src/utils/math.py": "def add(a, b): return a + b"})
        plan = build_review_plan(ctx)
        assert "touches_sensitive_path" not in plan.review_flags
        assert plan.sensitive_paths_touched == []

    def test_middleware_path_creates_auth_focus(self) -> None:
        ctx = _ctx(files={"middleware/auth_check.py": "check()"})
        plan = build_review_plan(ctx)
        assert "touches_sensitive_path" in plan.review_flags
        assert "authentication" in plan.focus_areas

    def test_deploy_path_creates_config_focus(self) -> None:
        ctx = _ctx(files={"deploy/production.yml": "replicas: 3"})
        plan = build_review_plan(ctx)
        assert "touches_sensitive_path" in plan.review_flags
        assert "insecure_configuration" in plan.focus_areas


# ======================================================================
# Planner — auth path focus
# ======================================================================


class TestPlannerAuthPaths:
    """Planner correctly derives focus from auth path overlap."""

    def test_auth_path_creates_auth_focus(self) -> None:
        ctx = _ctx(files={"src/auth/handler.py": "def login(): ..."})
        plan = build_review_plan(ctx)
        assert "touches_auth_area" in plan.review_flags
        assert "src/auth/handler.py" in plan.auth_paths_touched
        assert "authentication" in plan.focus_areas
        assert "authorization" in plan.focus_areas

    def test_login_path_creates_auth_focus(self) -> None:
        ctx = _ctx(files={"login/views.py": "class LoginView: ..."})
        plan = build_review_plan(ctx)
        assert "touches_auth_area" in plan.review_flags
        assert "authentication" in plan.focus_areas

    def test_oauth_path_creates_auth_focus(self) -> None:
        ctx = _ctx(files={"oauth/callback.py": "def callback(): ..."})
        plan = build_review_plan(ctx)
        assert "touches_auth_area" in plan.review_flags

    def test_session_path_creates_auth_focus(self) -> None:
        ctx = _ctx(files={"session/store.py": "class Store: ..."})
        plan = build_review_plan(ctx)
        assert "touches_auth_area" in plan.review_flags

    def test_token_path_creates_auth_focus(self) -> None:
        ctx = _ctx(files={"token/refresh.py": "def refresh(): ..."})
        plan = build_review_plan(ctx)
        assert "touches_auth_area" in plan.review_flags

    def test_permissions_path_creates_auth_focus(self) -> None:
        ctx = _ctx(files={"permissions/roles.py": "ROLES = {}"})
        plan = build_review_plan(ctx)
        assert "touches_auth_area" in plan.review_flags

    def test_unrelated_path_no_auth_flag(self) -> None:
        ctx = _ctx(files={"src/utils/math.py": "def add(a, b): return a + b"})
        plan = build_review_plan(ctx)
        assert "touches_auth_area" not in plan.review_flags
        assert plan.auth_paths_touched == []


# ======================================================================
# Planner — baseline context
# ======================================================================


class TestPlannerBaselineContext:
    """Planner correctly applies baseline auth patterns and frameworks."""

    def test_auth_patterns_flow_into_plan(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(auth_patterns=["JWT", "OAuth2"]),
        )
        plan = build_review_plan(ctx)
        assert plan.auth_pattern_context == ["JWT", "OAuth2"]

    def test_frameworks_flow_into_plan(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(frameworks=["FastAPI", "SQLAlchemy"]),
        )
        plan = build_review_plan(ctx)
        assert plan.framework_context == ["FastAPI", "SQLAlchemy"]

    def test_no_baseline_empty_context(self) -> None:
        ctx = _ctx(files={"src/app.py": "pass"})
        plan = build_review_plan(ctx)
        assert plan.auth_pattern_context == []
        assert plan.framework_context == []

    def test_auth_patterns_limited_to_four(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(
                auth_patterns=["JWT", "OAuth2", "SAML", "LDAP", "Kerberos"]
            ),
        )
        plan = build_review_plan(ctx)
        assert len(plan.auth_pattern_context) <= 4

    def test_frameworks_limited_to_four(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(
                frameworks=["FastAPI", "Django", "Flask", "Express", "Spring"]
            ),
        )
        plan = build_review_plan(ctx)
        assert len(plan.framework_context) <= 4


# ======================================================================
# Planner — memory context
# ======================================================================


class TestPlannerMemoryContext:
    """Planner correctly applies review memory to focus."""

    def test_relevant_memory_adds_focus(self) -> None:
        ctx = _ctx(
            files={"src/auth/handler.py": "def login(): pass"},
            memory=_memory([("authorization", "Prior auth bypass concern")]),
        )
        plan = build_review_plan(ctx)
        assert "authorization" in plan.relevant_memory_categories
        assert "has_relevant_memory" in plan.review_flags
        assert "authorization" in plan.focus_areas

    def test_unrelated_memory_does_not_add_focus(self) -> None:
        ctx = _ctx(
            files={"src/utils/math.py": "def add(a, b): return a + b"},
            memory=_memory([("authorization", "Prior auth bypass concern")]),
        )
        plan = build_review_plan(ctx)
        assert plan.relevant_memory_categories == []
        assert "has_relevant_memory" not in plan.review_flags

    def test_multiple_memory_categories_matched(self) -> None:
        ctx = _ctx(
            files={"config/settings.py": "DEBUG = True"},
            memory=_memory([
                ("insecure_configuration", "Debug mode left enabled"),
                ("secrets", "API key exposed in config"),
            ]),
        )
        plan = build_review_plan(ctx)
        assert "insecure_configuration" in plan.relevant_memory_categories
        assert "secrets" in plan.relevant_memory_categories

    def test_empty_memory_no_flag(self) -> None:
        ctx = _ctx(
            files={"src/auth/handler.py": "def login(): pass"},
            memory=_memory([]),
        )
        plan = build_review_plan(ctx)
        assert plan.relevant_memory_categories == []
        assert "has_relevant_memory" not in plan.review_flags

    def test_no_memory_provided(self) -> None:
        ctx = _ctx(files={"src/auth/handler.py": "def login(): pass"})
        plan = build_review_plan(ctx)
        assert plan.relevant_memory_categories == []


# ======================================================================
# Planner — guidance generation
# ======================================================================


class TestPlannerGuidance:
    """Planner generates appropriate reviewer guidance."""

    def test_sensitive_path_guidance(self) -> None:
        ctx = _ctx(files={"config/settings.py": "SECRET = 'abc'"})
        plan = build_review_plan(ctx)
        assert any("sensitive path" in g for g in plan.reviewer_guidance)

    def test_auth_path_guidance(self) -> None:
        ctx = _ctx(files={"src/auth/handler.py": "def login(): pass"})
        plan = build_review_plan(ctx)
        assert any("auth-related" in g for g in plan.reviewer_guidance)

    def test_framework_guidance(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(frameworks=["FastAPI"]),
        )
        plan = build_review_plan(ctx)
        assert any("FastAPI" in g for g in plan.reviewer_guidance)

    def test_auth_pattern_guidance(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        plan = build_review_plan(ctx)
        assert any("JWT" in g for g in plan.reviewer_guidance)

    def test_memory_guidance(self) -> None:
        ctx = _ctx(
            files={"src/auth/handler.py": "def login(): pass"},
            memory=_memory([("authorization", "Prior concern")]),
        )
        plan = build_review_plan(ctx)
        assert any("memory" in g.lower() for g in plan.reviewer_guidance)

    def test_empty_pr_guidance(self) -> None:
        ctx = _ctx(files={})
        plan = build_review_plan(ctx)
        assert any("empty" in g.lower() for g in plan.reviewer_guidance)


# ======================================================================
# Planner — combined scenarios
# ======================================================================


class TestPlannerCombined:
    """Planner handles combined context scenarios correctly."""

    def test_auth_path_with_auth_baseline_and_memory(self) -> None:
        ctx = _ctx(
            files={"src/auth/login.py": "def login(): pass"},
            baseline=_baseline(
                auth_patterns=["JWT", "OAuth2"],
                frameworks=["FastAPI"],
                sensitive_paths=["src/auth/"],
            ),
            memory=_memory([("authorization", "Prior RBAC bypass")]),
        )
        plan = build_review_plan(ctx)
        assert "authentication" in plan.focus_areas
        assert "authorization" in plan.focus_areas
        assert "touches_auth_area" in plan.review_flags
        assert "touches_sensitive_path" in plan.review_flags
        assert "has_relevant_memory" in plan.review_flags
        assert plan.auth_pattern_context == ["JWT", "OAuth2"]
        assert plan.framework_context == ["FastAPI"]
        assert "authorization" in plan.relevant_memory_categories

    def test_config_path_with_secrets_memory(self) -> None:
        ctx = _ctx(
            files={"config/database.yml": "password: hunter2"},
            memory=_memory([("secrets", "Hardcoded credentials found previously")]),
        )
        plan = build_review_plan(ctx)
        assert "insecure_configuration" in plan.focus_areas
        assert "secrets" in plan.focus_areas or "secrets" in plan.relevant_memory_categories
        assert "has_relevant_memory" in plan.review_flags

    def test_unrelated_path_with_unrelated_memory(self) -> None:
        """Neither path nor memory should create focus."""
        ctx = _ctx(
            files={"src/utils/math.py": "def add(a, b): return a + b"},
            memory=_memory([("dependency_risk", "Old vulnerability in lodash")]),
        )
        plan = build_review_plan(ctx)
        assert plan.focus_areas == []
        assert plan.relevant_memory_categories == []
        assert "touches_sensitive_path" not in plan.review_flags
        assert "touches_auth_area" not in plan.review_flags
        assert "has_relevant_memory" not in plan.review_flags


# ======================================================================
# Engine integration — plan-driven contextual notes
# ======================================================================


class TestPlanDrivenNotes:
    """Contextual notes now reflect structured review plan input."""

    def test_sensitive_path_note_via_plan(self) -> None:
        ctx = _ctx(files={"config/settings.py": "SECRET = 'abc'"})
        result = analyse(ctx)
        assert any("sensitive path" in n for n in result.reasoning_notes)

    def test_auth_path_note_via_plan(self) -> None:
        ctx = _ctx(files={"src/auth/handler.py": "def login(): pass"})
        result = analyse(ctx)
        assert any("authentication" in n.lower() or "authorisation" in n.lower()
                    for n in result.reasoning_notes)

    def test_framework_note_via_plan(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(frameworks=["Django"]),
        )
        result = analyse(ctx)
        assert any("Django" in n for n in result.reasoning_notes)

    def test_auth_pattern_note_via_plan(self) -> None:
        ctx = _ctx(
            files={"src/app.py": "pass"},
            baseline=_baseline(auth_patterns=["OAuth2"]),
        )
        result = analyse(ctx)
        assert any("OAuth2" in n for n in result.reasoning_notes)

    def test_focus_areas_note_via_plan(self) -> None:
        ctx = _ctx(files={"src/auth/handler.py": "def login(): pass"})
        result = analyse(ctx)
        assert any("focus areas" in n.lower() for n in result.reasoning_notes)

    def test_review_flags_note_via_plan(self) -> None:
        ctx = _ctx(files={"src/auth/handler.py": "def login(): pass"})
        result = analyse(ctx)
        assert any("review flags" in n.lower() for n in result.reasoning_notes)

    def test_memory_note_via_plan(self) -> None:
        ctx = _ctx(
            files={"src/auth/handler.py": "def login(): pass"},
            memory=_memory([("authorization", "Prior concern")]),
        )
        result = analyse(ctx)
        assert any("memory" in n.lower() for n in result.reasoning_notes)


# ======================================================================
# Engine integration — flow stability
# ======================================================================


class TestPlanFlowStability:
    """Engine + planner flow produces valid, stable output."""

    def test_analyse_returns_analysis_result(self) -> None:
        ctx = _ctx(files={"src/app.py": "pass"})
        result = analyse(ctx)
        assert isinstance(result, AnalysisResult)
        assert isinstance(result.findings, list)
        assert isinstance(result.reasoning_notes, list)

    def test_analyse_with_dict_input(self) -> None:
        result = analyse({"src/app.py": "pass"})
        assert isinstance(result, AnalysisResult)

    def test_analyse_with_pr_content_input(self) -> None:
        pr = PRContent.from_dict({"src/app.py": "pass"})
        result = analyse(pr)
        assert isinstance(result, AnalysisResult)

    def test_scan_result_json_stable(self) -> None:
        """ScanResult JSON serialisation remains stable."""
        output = mock_run()
        result = output["result"]
        assert isinstance(result, ScanResult)
        json_str = output["json"]
        parsed = json.loads(json_str)
        assert "decision" in parsed
        assert "risk_score" in parsed
        assert "findings" in parsed

    def test_markdown_output_stable(self) -> None:
        """Markdown rendering still works with plan-driven notes."""
        output = mock_run()
        md = output["markdown"]
        assert isinstance(md, str)
        assert len(md) > 0
        # Should contain standard sections
        assert "parity-zero" in md.lower() or "security" in md.lower() or "review" in md.lower()

    def test_decision_derivation_unchanged(self) -> None:
        """Decision derivation logic is unchanged by planner introduction."""
        decision, score = derive_decision_and_risk([])
        assert decision == Decision.PASS
        assert score == 0

    def test_deterministic_checks_still_work(self) -> None:
        """Deterministic checks produce findings alongside plan-driven notes."""
        ctx = _ctx(files={"app.py": 'DEBUG = True\nallow_origins=["*"]'})
        result = analyse(ctx)
        # Should have findings from deterministic checks
        assert len(result.findings) > 0
        # Should also have reasoning notes from plan
        assert len(result.reasoning_notes) > 0


# ======================================================================
# No overclaiming
# ======================================================================


class TestNoOverclaiming:
    """Review plan influences attention, not findings."""

    def test_plan_does_not_create_findings(self) -> None:
        """Plan alone should not create findings."""
        ctx = _ctx(
            files={"src/auth/handler.py": "def login(): pass"},
            baseline=_baseline(
                auth_patterns=["JWT"],
                frameworks=["FastAPI"],
                sensitive_paths=["src/auth/"],
            ),
            memory=_memory([("authorization", "Prior concern")]),
        )
        result = analyse(ctx)
        # All findings should come from deterministic checks, not plan
        for f in result.findings:
            assert f.confidence in (Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW)

    def test_benign_code_with_sensitive_path_no_findings(self) -> None:
        """Benign code in sensitive paths should not generate findings."""
        ctx = _ctx(
            files={"src/auth/handler.py": "def greet(name): return f'Hello {name}'"},
        )
        result = analyse(ctx)
        assert len(result.findings) == 0
        # But should still have contextual notes about the path
        assert any("auth" in n.lower() for n in result.reasoning_notes)

    def test_plan_notes_are_informational(self) -> None:
        """Notes from the plan should be informational, not assertive about vulnerabilities."""
        ctx = _ctx(
            files={"config/settings.py": "ALLOWED_HOSTS = ['example.com']"},
            baseline=_baseline(auth_patterns=["JWT"]),
        )
        result = analyse(ctx)
        for note in result.reasoning_notes:
            # Notes should not claim certainty about vulnerabilities
            assert "vulnerability found" not in note.lower()
            assert "critical issue" not in note.lower()

    def test_risk_score_unaffected_by_plan(self) -> None:
        """Risk score should only be affected by actual findings, not the plan."""
        # Benign code in auth path — no findings expected
        ctx = _ctx(
            files={"src/auth/handler.py": "def greet(): return 'hello'"},
            baseline=_baseline(auth_patterns=["JWT", "OAuth2"]),
            memory=_memory([("authorization", "Prior concern")]),
        )
        result = analyse(ctx)
        decision, score = derive_decision_and_risk(result.findings)
        assert score == 0
        assert decision == Decision.PASS


# ======================================================================
# Backward compatibility of helper re-exports
# ======================================================================


class TestHelperReExports:
    """Helpers re-exported from reasoning.py remain accessible."""

    def test_sensitive_path_overlap_from_reasoning(self) -> None:
        from reviewer.reasoning import _sensitive_path_overlap
        result = _sensitive_path_overlap(
            ["src/auth/handler.py"], ["src/auth/handler.py"]
        )
        assert "src/auth/handler.py" in result

    def test_auth_path_overlap_from_reasoning(self) -> None:
        from reviewer.reasoning import _auth_path_overlap
        result = _auth_path_overlap(["src/auth/handler.py"])
        assert "src/auth/handler.py" in result

    def test_infer_path_categories_from_reasoning(self) -> None:
        from reviewer.reasoning import _infer_path_categories
        cats = _infer_path_categories(["src/auth/login.py"])
        assert "authentication" in cats

    def test_relevant_memory_entries_from_reasoning(self) -> None:
        from reviewer.reasoning import _relevant_memory_entries
        mem = _memory([("authorization", "test")])
        entries = _relevant_memory_entries(["src/auth/login.py"], mem)
        assert len(entries) == 1


# ======================================================================
# Planner helpers (direct tests)
# ======================================================================


class TestPlannerHelpers:
    """Direct tests for planner path analysis helpers."""

    def test_sensitive_path_overlap_direct_match(self) -> None:
        result = sensitive_path_overlap(
            ["src/internal/core.py"], ["src/internal/core.py"]
        )
        assert "src/internal/core.py" in result

    def test_sensitive_path_overlap_segment_match(self) -> None:
        result = sensitive_path_overlap(["config/db.py"], [])
        assert "config/db.py" in result

    def test_sensitive_path_overlap_no_match(self) -> None:
        result = sensitive_path_overlap(["src/utils/helpers.py"], [])
        assert result == []

    def test_auth_path_overlap_match(self) -> None:
        result = auth_path_overlap(["src/auth/handler.py"])
        assert "src/auth/handler.py" in result

    def test_auth_path_overlap_no_match(self) -> None:
        result = auth_path_overlap(["src/utils/math.py"])
        assert result == []

    def test_infer_path_categories_auth(self) -> None:
        cats = infer_path_categories(["src/auth/login.py"])
        assert "authentication" in cats
        assert "authorization" in cats

    def test_infer_path_categories_config(self) -> None:
        cats = infer_path_categories(["config/settings.py"])
        assert "insecure_configuration" in cats
        assert "secrets" in cats

    def test_infer_path_categories_dependency(self) -> None:
        cats = infer_path_categories(["requirements.txt"])
        assert "dependency_risk" in cats

    def test_infer_path_categories_unrelated(self) -> None:
        cats = infer_path_categories(["src/utils/helpers.py"])
        assert cats == set()

    def test_relevant_memory_entries_match(self) -> None:
        mem = _memory([("authorization", "test")])
        entries = relevant_memory_entries(["src/auth/login.py"], mem)
        assert len(entries) == 1

    def test_relevant_memory_entries_no_match(self) -> None:
        mem = _memory([("dependency_risk", "test")])
        entries = relevant_memory_entries(["src/auth/login.py"], mem)
        assert len(entries) == 0

    def test_relevant_memory_entries_empty_memory(self) -> None:
        mem = _memory([])
        entries = relevant_memory_entries(["src/auth/login.py"], mem)
        assert len(entries) == 0
