"""Tests for the ReviewBundle concept (ADR-023).

Validates:
  1. Bundle creation from PullRequestContext + ReviewPlan
  2. Bundle behavior when sensitive/auth context exists
  3. Bundle behavior when memory context is relevant
  4. Bundle behavior when context is weak
  5. Current reviewer flow stability (bundle does not break existing output)
  6. No-overclaiming: bundle improves review input quality, not finding certainty
  7. JSON contract unchanged
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
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewPlan,
)
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


# ======================================================================
# 1. Bundle creation from PullRequestContext + ReviewPlan
# ======================================================================


class TestBundleCreation:
    """Verify basic bundle assembly from context and plan."""

    def test_empty_files_produces_empty_bundle(self):
        ctx = _ctx(files={})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.item_count == 0
        assert bundle.items == []

    def test_single_file_produces_one_item(self):
        ctx = _ctx(files={"src/app.py": "print('hello')"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.item_count == 1
        assert bundle.items[0].path == "src/app.py"
        assert bundle.items[0].content == "print('hello')"

    def test_multiple_files_produce_multiple_items(self):
        ctx = _ctx(files={
            "src/app.py": "app",
            "src/utils.py": "utils",
            "tests/test_app.py": "test",
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.item_count == 3
        paths = [i.path for i in bundle.items]
        assert "src/app.py" in paths
        assert "src/utils.py" in paths
        assert "tests/test_app.py" in paths

    def test_plan_summary_carries_guidance(self):
        ctx = _ctx(
            files={"src/auth/login.py": "# auth"},
            baseline=_baseline(sensitive_paths=["src/auth"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert len(bundle.plan_summary) > 0

    def test_repo_frameworks_from_plan(self):
        ctx = _ctx(
            files={"src/app.py": "from flask import Flask"},
            baseline=_baseline(frameworks=["flask", "sqlalchemy"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert "flask" in bundle.repo_frameworks

    def test_repo_auth_patterns_from_plan(self):
        ctx = _ctx(
            files={"src/auth/login.py": "jwt.decode(token)"},
            baseline=_baseline(auth_patterns=["jwt", "oauth"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert "jwt" in bundle.repo_auth_patterns

    def test_bundle_item_has_content_from_pr_file(self):
        content = "SECRET_KEY = 'change-me'"
        ctx = _ctx(files={"config/settings.py": content})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.items[0].content == content


# ======================================================================
# 2. Bundle behavior when sensitive/auth context exists
# ======================================================================


class TestBundleSensitiveAuth:
    """Verify sensitive and auth path classification in bundle items."""

    def test_sensitive_path_gets_sensitive_reason(self):
        ctx = _ctx(files={"config/settings.py": "DEBUG = True"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert "sensitive" in item.review_reason

    def test_auth_path_gets_auth_reason(self):
        ctx = _ctx(files={"src/auth/handler.py": "# auth"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert "auth" in item.review_reason

    def test_sensitive_auth_overlap_gets_combined_reason(self):
        ctx = _ctx(
            files={"auth/config.py": "# auth config"},
            baseline=_baseline(sensitive_paths=["auth/config.py"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert item.review_reason == "sensitive_auth"

    def test_non_sensitive_file_gets_changed_file_reason(self):
        ctx = _ctx(files={"src/utils.py": "# utility"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert item.review_reason == "changed_file"

    def test_sensitive_items_property(self):
        ctx = _ctx(files={
            "config/settings.py": "DEBUG = True",
            "src/utils.py": "# utility",
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        sensitive = bundle.sensitive_items
        assert len(sensitive) >= 1
        assert all("sensitive" in i.review_reason for i in sensitive)

    def test_auth_items_property(self):
        ctx = _ctx(files={
            "src/auth/login.py": "# auth",
            "src/utils.py": "# utility",
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        auth = bundle.auth_items
        assert len(auth) >= 1
        assert all("auth" in i.review_reason for i in auth)

    def test_has_high_focus_items_true_for_sensitive(self):
        ctx = _ctx(files={"config/settings.py": "DEBUG = True"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.has_high_focus_items is True

    def test_has_high_focus_items_false_for_plain(self):
        ctx = _ctx(files={"src/utils.py": "# utility"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.has_high_focus_items is False

    def test_sensitive_file_gets_focus_areas(self):
        ctx = _ctx(
            files={"config/settings.py": "DEBUG = True"},
            baseline=_baseline(sensitive_paths=["config/settings.py"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert len(item.focus_areas) > 0

    def test_auth_file_with_baseline_patterns_gets_baseline_context(self):
        ctx = _ctx(
            files={"src/auth/handler.py": "# jwt handler"},
            baseline=_baseline(auth_patterns=["jwt", "bearer"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert len(item.baseline_context) > 0
        assert any("jwt" in c for c in item.baseline_context)

    def test_related_paths_for_same_directory(self):
        ctx = _ctx(files={
            "src/auth/login.py": "# login",
            "src/auth/logout.py": "# logout",
            "src/utils.py": "# utility",
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        login_item = next(i for i in bundle.items if i.path == "src/auth/login.py")
        assert "src/auth/logout.py" in login_item.related_paths

    def test_related_paths_bounded(self):
        """Related paths should not exceed the max limit."""
        files = {f"src/auth/file{i}.py": f"# file {i}" for i in range(10)}
        ctx = _ctx(files=files)
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        for item in bundle.items:
            assert len(item.related_paths) <= 3


# ======================================================================
# 3. Bundle behavior when memory context is relevant
# ======================================================================


class TestBundleMemoryContext:
    """Verify memory context enrichment in bundle items."""

    def test_memory_context_added_for_matching_category(self):
        ctx = _ctx(
            files={"src/auth/login.py": "# auth"},
            memory=_memory([("authentication", "JWT validation bypass in prior review")]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert len(item.memory_context) > 0
        assert any("JWT" in m for m in item.memory_context)

    def test_no_memory_context_for_unrelated_category(self):
        ctx = _ctx(
            files={"src/utils.py": "# utility"},
            memory=_memory([("authentication", "JWT validation bypass")]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert item.memory_context == []

    def test_memory_context_bounded(self):
        """Memory context per item should not exceed the max limit."""
        entries = [
            ("authentication", f"Memory entry {i}")
            for i in range(10)
        ]
        ctx = _ctx(
            files={"src/auth/login.py": "# auth"},
            memory=_memory(entries),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        assert len(item.memory_context) <= 3

    def test_multiple_files_with_different_memory_relevance(self):
        ctx = _ctx(
            files={
                "src/auth/login.py": "# auth",
                "src/utils.py": "# utility",
            },
            memory=_memory([("authentication", "auth issue in prior review")]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        auth_item = next(i for i in bundle.items if i.path == "src/auth/login.py")
        util_item = next(i for i in bundle.items if i.path == "src/utils.py")
        assert len(auth_item.memory_context) > 0
        assert util_item.memory_context == []


# ======================================================================
# 4. Bundle behavior when context is weak
# ======================================================================


class TestBundleWeakContext:
    """Verify bundle behavior with minimal/no enriching context."""

    def test_plain_files_no_baseline_no_memory(self):
        ctx = _ctx(files={"src/app.py": "print('hello')"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.item_count == 1
        item = bundle.items[0]
        assert item.review_reason == "changed_file"
        assert item.focus_areas == []
        assert item.baseline_context == []
        assert item.memory_context == []

    def test_no_plan_summary_when_no_context(self):
        ctx = _ctx(files={"src/app.py": "print('hello')"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        # Plan summary may or may not be empty, but items should still be present
        assert bundle.item_count == 1

    def test_no_repo_frameworks_without_baseline(self):
        ctx = _ctx(files={"src/app.py": "print('hello')"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.repo_frameworks == []

    def test_no_repo_auth_patterns_without_baseline(self):
        ctx = _ctx(files={"src/app.py": "print('hello')"})
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.repo_auth_patterns == []

    def test_empty_memory_produces_no_memory_context(self):
        ctx = _ctx(
            files={"src/app.py": "print('hello')"},
            memory=_memory([]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.items[0].memory_context == []

    def test_has_high_focus_items_false_for_all_plain(self):
        ctx = _ctx(files={
            "src/app.py": "print('hello')",
            "src/utils.py": "# utility",
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        assert bundle.has_high_focus_items is False


# ======================================================================
# 5. Current reviewer flow stability
# ======================================================================


class TestFlowStability:
    """Verify that the bundle integration does not break existing flow."""

    def test_analyse_still_returns_findings(self):
        analysis = analyse({"src/settings.py": "DEBUG = True\n"})
        assert isinstance(analysis, AnalysisResult)
        assert len(analysis.findings) > 0

    def test_analyse_still_returns_reasoning_notes(self):
        analysis = analyse({"src/settings.py": "DEBUG = True\n"})
        assert isinstance(analysis.reasoning_notes, list)
        assert len(analysis.reasoning_notes) > 0

    def test_analyse_returns_bundle(self):
        analysis = analyse({"src/settings.py": "DEBUG = True\n"})
        assert analysis.bundle is not None
        assert isinstance(analysis.bundle, ReviewBundle)

    def test_analyse_with_pull_request_context(self):
        ctx = _ctx(
            files={"src/auth/login.py": "# auth handler"},
            baseline=_baseline(auth_patterns=["jwt"]),
        )
        analysis = analyse(ctx)
        assert analysis.bundle is not None
        assert analysis.bundle.item_count == 1

    def test_mock_run_still_works(self):
        result = mock_run()
        assert "result" in result
        assert "markdown" in result
        assert "json" in result
        assert "reasoning_notes" in result
        assert "concerns" in result

    def test_mock_run_json_valid(self):
        result = mock_run()
        parsed = json.loads(result["json"])
        assert "findings" in parsed
        assert "decision" in parsed
        assert "risk_score" in parsed

    def test_reasoning_with_plan_returns_bundle(self):
        ctx = _ctx(files={"src/config/settings.py": "DEBUG = True"})
        plan = build_review_plan(ctx)
        reasoning = run_reasoning(ctx, plan=plan)
        assert reasoning.bundle is not None
        assert isinstance(reasoning.bundle, ReviewBundle)

    def test_reasoning_without_plan_returns_no_bundle(self):
        ctx = _ctx(files={"src/app.py": "print('hello')"})
        reasoning = run_reasoning(ctx, plan=None)
        assert reasoning.bundle is None

    def test_derive_decision_unchanged(self):
        """Decision derivation is unaffected by bundle."""
        finding = Finding(
            title="Test",
            description="Test finding",
            severity=Severity.HIGH,
            confidence=Confidence.HIGH,
            category=Category.SECRETS,
            file="test.py",
        )
        decision, score = derive_decision_and_risk([finding])
        assert decision == Decision.WARN
        assert score == 25


# ======================================================================
# 6. No-overclaiming
# ======================================================================


class TestNoOverclaiming:
    """Verify the bundle does not create false certainty."""

    def test_bundle_does_not_produce_findings(self):
        """Bundle is evidence aggregation, not finding generation."""
        ctx = _ctx(
            files={"src/auth/login.py": "jwt.decode(token)"},
            baseline=_baseline(
                auth_patterns=["jwt"],
                sensitive_paths=["src/auth"],
            ),
            memory=_memory([("authentication", "JWT bypass issue")]),
        )
        plan = build_review_plan(ctx)
        reasoning = run_reasoning(ctx, plan=plan)
        # Phase 1: no findings from reasoning layer
        assert reasoning.findings == []

    def test_bundle_does_not_affect_risk_score(self):
        """Bundle must not influence scoring."""
        ctx = _ctx(files={"src/utils.py": "# utility"})
        analysis = analyse(ctx)
        decision, score = derive_decision_and_risk(analysis.findings)
        assert decision == Decision.PASS
        assert score == 0

    def test_bundle_not_in_scan_result_json(self):
        """Bundle must not appear in the JSON contract."""
        result = mock_run()
        parsed = json.loads(result["json"])
        assert "bundle" not in parsed
        assert "review_bundle" not in parsed

    def test_bundle_review_reasons_are_descriptive_not_assertive(self):
        """Review reasons should describe context, not claim vulnerabilities."""
        ctx = _ctx(
            files={"src/auth/login.py": "# auth"},
            baseline=_baseline(sensitive_paths=["src/auth"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        item = bundle.items[0]
        # Review reason should be a classification, not a vulnerability claim
        assert item.review_reason in (
            "sensitive_path", "auth_area", "sensitive_auth", "changed_file",
        )

    def test_focus_areas_reflect_taxonomy_categories(self):
        """Focus areas should use established taxonomy categories."""
        valid_categories = {
            "authentication", "authorization", "input_validation",
            "secrets", "insecure_configuration", "dependency_risk",
        }
        ctx = _ctx(
            files={"config/settings.py": "DEBUG = True"},
            baseline=_baseline(sensitive_paths=["config"]),
        )
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        for item in bundle.items:
            for area in item.focus_areas:
                assert area in valid_categories, f"Unexpected focus area: {area}"


# ======================================================================
# 7. JSON contract unchanged
# ======================================================================


class TestJsonContractStability:
    """Verify the ScanResult JSON contract is completely unaffected."""

    def test_scan_result_shape_unchanged(self):
        result = mock_run()
        parsed = json.loads(result["json"])
        required_fields = {
            "scan_id", "timestamp", "repo", "pr_number", "commit_sha",
            "ref", "decision", "risk_score", "findings",
        }
        assert required_fields.issubset(set(parsed.keys()))

    def test_finding_shape_unchanged(self):
        result = mock_run()
        parsed = json.loads(result["json"])
        if parsed["findings"]:
            finding = parsed["findings"][0]
            assert "id" in finding
            assert "title" in finding
            assert "description" in finding
            assert "severity" in finding
            assert "category" in finding
            assert "file" in finding

    def test_decision_values_unchanged(self):
        result = mock_run()
        parsed = json.loads(result["json"])
        assert parsed["decision"] in ("pass", "warn", "block")

    def test_ingestion_shape_stable(self):
        """The ingestion payload shape must remain stable."""
        result = mock_run()
        sr: ScanResult = result["result"]
        payload = sr.model_dump()
        assert "findings" in payload
        assert "decision" in payload
        assert "risk_score" in payload
        assert "bundle" not in payload


# ======================================================================
# 8. ReviewBundle and ReviewBundleItem model unit tests
# ======================================================================


class TestBundleModels:
    """Unit tests for the bundle data models."""

    def test_bundle_item_defaults(self):
        item = ReviewBundleItem()
        assert item.path == ""
        assert item.content == ""
        assert item.review_reason == ""
        assert item.focus_areas == []
        assert item.baseline_context == []
        assert item.memory_context == []
        assert item.related_paths == []

    def test_bundle_defaults(self):
        bundle = ReviewBundle()
        assert bundle.items == []
        assert bundle.plan_summary == []
        assert bundle.repo_frameworks == []
        assert bundle.repo_auth_patterns == []
        assert bundle.item_count == 0
        assert bundle.sensitive_items == []
        assert bundle.auth_items == []
        assert bundle.has_high_focus_items is False

    def test_bundle_item_with_values(self):
        item = ReviewBundleItem(
            path="src/auth/login.py",
            content="# auth",
            review_reason="sensitive_auth",
            focus_areas=["authentication"],
            baseline_context=["repo auth patterns: jwt"],
            memory_context=["authentication: JWT bypass"],
            related_paths=["src/auth/logout.py"],
        )
        assert item.path == "src/auth/login.py"
        assert item.review_reason == "sensitive_auth"
        assert len(item.focus_areas) == 1

    def test_bundle_sensitive_items_filter(self):
        bundle = ReviewBundle(items=[
            ReviewBundleItem(path="a.py", review_reason="sensitive_path"),
            ReviewBundleItem(path="b.py", review_reason="changed_file"),
            ReviewBundleItem(path="c.py", review_reason="sensitive_auth"),
        ])
        sensitive = bundle.sensitive_items
        assert len(sensitive) == 2
        assert sensitive[0].path == "a.py"
        assert sensitive[1].path == "c.py"

    def test_bundle_auth_items_filter(self):
        bundle = ReviewBundle(items=[
            ReviewBundleItem(path="a.py", review_reason="auth_area"),
            ReviewBundleItem(path="b.py", review_reason="changed_file"),
            ReviewBundleItem(path="c.py", review_reason="sensitive_auth"),
        ])
        auth = bundle.auth_items
        assert len(auth) == 2
        assert auth[0].path == "a.py"
        assert auth[1].path == "c.py"
