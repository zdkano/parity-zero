"""Tests for the parity-zero reasoning prompt/input builder (ADR-025).

Covers:
- Building a reasoning request from minimal context
- Building a reasoning request with full context (plan, bundle, baseline, memory)
- File summaries derived from bundle items vs raw file list
- Plan context propagation to request
- Baseline context propagation to request
- Memory context propagation to request
- Concern and observation context propagation
- Deterministic findings context propagation
- Empty/edge cases
"""

from __future__ import annotations

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
from reviewer.prompt_builder import build_reasoning_request
from reviewer.providers import ReasoningRequest
from schemas.findings import Category, Confidence, Finding, Severity


# ======================================================================
# Helpers
# ======================================================================


def _make_ctx(
    files: dict[str, str] | None = None,
    frameworks: list[str] | None = None,
    auth_patterns: list[str] | None = None,
    memory_entries: list[tuple[str, str]] | None = None,
) -> PullRequestContext:
    """Build a PullRequestContext with optional baseline and memory."""
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


def _make_plan(**kwargs) -> ReviewPlan:
    return ReviewPlan(**kwargs)


def _make_bundle(items: list[dict] | None = None) -> ReviewBundle:
    bundle_items = []
    if items:
        for item in items:
            bundle_items.append(ReviewBundleItem(**item))
    return ReviewBundle(items=bundle_items)


def _make_finding(
    category: str = "secrets",
    title: str = "Hardcoded secret",
    file: str = "config.py",
) -> Finding:
    return Finding(
        category=Category(category),
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        title=title,
        description="Test finding",
        file=file,
    )


# ======================================================================
# Minimal context tests
# ======================================================================


class TestMinimalContext:
    """Tests for building a reasoning request from minimal context."""

    def test_minimal_request_has_file_summaries(self):
        ctx = _make_ctx(files={"a.py": "content"})
        req = build_reasoning_request(ctx)
        assert isinstance(req, ReasoningRequest)
        assert req.file_count == 1
        assert req.changed_files_summary[0]["path"] == "a.py"

    def test_minimal_request_has_no_plan(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx)
        assert not req.has_plan_context
        assert req.plan_focus_areas == []
        assert req.plan_flags == []

    def test_minimal_request_has_no_baseline(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx)
        assert not req.has_baseline_context

    def test_minimal_request_has_no_memory(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx)
        assert not req.has_memory_context

    def test_multiple_files(self):
        ctx = _make_ctx(files={"a.py": "x", "b.py": "y", "c.py": "z"})
        req = build_reasoning_request(ctx)
        assert req.file_count == 3
        paths = [s["path"] for s in req.changed_files_summary]
        assert set(paths) == {"a.py", "b.py", "c.py"}

    def test_empty_files(self):
        ctx = PullRequestContext(pr_content=PRContent())
        req = build_reasoning_request(ctx)
        assert req.file_count == 0

    def test_file_summaries_have_default_review_reason(self):
        ctx = _make_ctx(files={"x.py": "code"})
        req = build_reasoning_request(ctx)
        assert req.changed_files_summary[0]["review_reason"] == "changed_file"


# ======================================================================
# Plan context tests
# ======================================================================


class TestPlanContext:
    """Tests for plan context propagation to reasoning request."""

    def test_plan_focus_areas_propagated(self):
        ctx = _make_ctx()
        plan = _make_plan(focus_areas=["authentication", "secrets"])
        req = build_reasoning_request(ctx, plan=plan)
        assert req.plan_focus_areas == ["authentication", "secrets"]
        assert req.has_plan_context

    def test_plan_flags_propagated(self):
        ctx = _make_ctx()
        plan = _make_plan(review_flags=["touches_sensitive_path"])
        req = build_reasoning_request(ctx, plan=plan)
        assert req.plan_flags == ["touches_sensitive_path"]
        assert req.has_plan_context

    def test_plan_guidance_propagated(self):
        ctx = _make_ctx()
        plan = _make_plan(reviewer_guidance=["Check auth boundaries"])
        req = build_reasoning_request(ctx, plan=plan)
        assert req.plan_guidance == ["Check auth boundaries"]

    def test_no_plan_means_no_plan_context(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx, plan=None)
        assert not req.has_plan_context


# ======================================================================
# Bundle context tests
# ======================================================================


class TestBundleContext:
    """Tests for bundle-derived file summaries."""

    def test_bundle_items_used_for_file_summaries(self):
        ctx = _make_ctx(files={"auth.py": "code"})
        bundle = _make_bundle(items=[
            {
                "path": "auth.py",
                "content": "code",
                "review_reason": "auth_area",
                "focus_areas": ["authentication"],
            }
        ])
        req = build_reasoning_request(ctx, bundle=bundle)
        assert req.file_count == 1
        summary = req.changed_files_summary[0]
        assert summary["path"] == "auth.py"
        assert summary["review_reason"] == "auth_area"
        assert "authentication" in summary["focus_areas"]

    def test_empty_bundle_falls_back_to_raw_files(self):
        ctx = _make_ctx(files={"x.py": "code"})
        bundle = _make_bundle(items=[])
        req = build_reasoning_request(ctx, bundle=bundle)
        assert req.file_count == 1
        assert req.changed_files_summary[0]["review_reason"] == "changed_file"

    def test_none_bundle_falls_back_to_raw_files(self):
        ctx = _make_ctx(files={"x.py": "code"})
        req = build_reasoning_request(ctx, bundle=None)
        assert req.file_count == 1
        assert req.changed_files_summary[0]["review_reason"] == "changed_file"


# ======================================================================
# Baseline context tests
# ======================================================================


class TestBaselineContext:
    """Tests for baseline profile propagation to reasoning request."""

    def test_frameworks_propagated(self):
        ctx = _make_ctx(frameworks=["django", "fastapi"])
        req = build_reasoning_request(ctx)
        assert req.baseline_frameworks == ["django", "fastapi"]
        assert req.has_baseline_context

    def test_auth_patterns_propagated(self):
        ctx = _make_ctx(auth_patterns=["jwt", "oauth"])
        req = build_reasoning_request(ctx)
        assert req.baseline_auth_patterns == ["jwt", "oauth"]
        assert req.has_baseline_context

    def test_no_baseline_means_no_baseline_context(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx)
        assert not req.has_baseline_context
        assert req.baseline_frameworks == []
        assert req.baseline_auth_patterns == []


# ======================================================================
# Memory context tests
# ======================================================================


class TestMemoryContext:
    """Tests for review memory propagation to reasoning request."""

    def test_memory_categories_propagated(self):
        ctx = _make_ctx(memory_entries=[("secrets", "Prior secret leak")])
        req = build_reasoning_request(ctx)
        assert "secrets" in req.memory_categories
        assert req.has_memory_context

    def test_memory_entries_propagated(self):
        ctx = _make_ctx(memory_entries=[("secrets", "Prior secret leak")])
        req = build_reasoning_request(ctx)
        assert len(req.memory_entries) == 1
        assert req.memory_entries[0]["category"] == "secrets"
        assert req.memory_entries[0]["summary"] == "Prior secret leak"

    def test_no_memory_means_no_memory_context(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx)
        assert not req.has_memory_context
        assert req.memory_categories == []
        assert req.memory_entries == []

    def test_memory_entries_bounded(self):
        """Memory entries are bounded to prevent excessive context."""
        entries = [(f"cat_{i}", f"Summary {i}") for i in range(20)]
        ctx = _make_ctx(memory_entries=entries)
        req = build_reasoning_request(ctx)
        assert len(req.memory_entries) <= 10


# ======================================================================
# Concerns and observations context tests
# ======================================================================


class TestConcernsAndObservations:
    """Tests for existing concerns/observations propagation."""

    def test_concerns_propagated(self):
        ctx = _make_ctx()
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Auth concern",
                summary="Auth boundary may be affected",
            )
        ]
        req = build_reasoning_request(ctx, concerns=concerns)
        assert len(req.existing_concerns) == 1
        assert req.existing_concerns[0]["category"] == "authentication"
        assert req.existing_concerns[0]["title"] == "Auth concern"

    def test_observations_propagated(self):
        ctx = _make_ctx()
        observations = [
            ReviewObservation(
                path="auth.py",
                title="Auth observation",
                summary="File touches auth boundary",
            )
        ]
        req = build_reasoning_request(ctx, observations=observations)
        assert len(req.existing_observations) == 1
        assert req.existing_observations[0]["path"] == "auth.py"

    def test_no_concerns_means_empty(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx, concerns=None)
        assert req.existing_concerns == []

    def test_no_observations_means_empty(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx, observations=None)
        assert req.existing_observations == []


# ======================================================================
# Deterministic findings context tests
# ======================================================================


class TestDeterministicFindings:
    """Tests for deterministic findings propagation to reasoning request."""

    def test_findings_propagated(self):
        ctx = _make_ctx()
        findings = [_make_finding()]
        req = build_reasoning_request(ctx, deterministic_findings=findings)
        assert len(req.deterministic_findings_summary) == 1
        assert req.deterministic_findings_summary[0]["category"] == "secrets"
        assert req.deterministic_findings_summary[0]["title"] == "Hardcoded secret"
        assert req.deterministic_findings_summary[0]["file"] == "config.py"

    def test_no_findings_means_empty(self):
        ctx = _make_ctx()
        req = build_reasoning_request(ctx, deterministic_findings=None)
        assert req.deterministic_findings_summary == []

    def test_multiple_findings(self):
        ctx = _make_ctx()
        findings = [
            _make_finding(category="secrets", title="Secret 1", file="a.py"),
            _make_finding(category="insecure_configuration", title="Debug mode", file="b.py"),
        ]
        req = build_reasoning_request(ctx, deterministic_findings=findings)
        assert len(req.deterministic_findings_summary) == 2


# ======================================================================
# Full context assembly tests
# ======================================================================


class TestFullContextAssembly:
    """Tests for building a complete reasoning request from full context."""

    def test_full_context_request(self):
        ctx = _make_ctx(
            files={"auth.py": "auth code", "config.py": "config code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
            memory_entries=[("authentication", "Prior auth issue")],
        )
        plan = _make_plan(
            focus_areas=["authentication"],
            review_flags=["touches_auth_path"],
            reviewer_guidance=["Check auth boundaries"],
        )
        bundle = _make_bundle(items=[
            {
                "path": "auth.py",
                "content": "auth code",
                "review_reason": "auth_area",
                "focus_areas": ["authentication"],
            },
            {
                "path": "config.py",
                "content": "config code",
                "review_reason": "changed_file",
                "focus_areas": [],
            },
        ])
        concerns = [
            ReviewConcern(category="authentication", title="Auth concern", summary="desc"),
        ]
        observations = [
            ReviewObservation(path="auth.py", title="Auth obs", summary="desc"),
        ]
        findings = [_make_finding()]

        req = build_reasoning_request(
            ctx,
            plan=plan,
            bundle=bundle,
            concerns=concerns,
            observations=observations,
            deterministic_findings=findings,
        )

        # Verify all context is present
        assert req.file_count == 2
        assert req.has_plan_context
        assert req.has_baseline_context
        assert req.has_memory_context
        assert len(req.existing_concerns) == 1
        assert len(req.existing_observations) == 1
        assert len(req.deterministic_findings_summary) == 1
        assert req.plan_focus_areas == ["authentication"]
        assert req.baseline_frameworks == ["django"]
        assert req.baseline_auth_patterns == ["jwt"]
        assert "authentication" in req.memory_categories
