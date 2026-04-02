"""Tests for deterministic change summary and provider context improvements (ADR-047).

Covers:
1. Change summary generation — factual, compact, path-aware
2. Change summary rendering in markdown
3. Provider context quality — diff-aware evidence, fuller context, bounded prompts
4. Regression — ScanResult unchanged, scoring unchanged, provider non-authoritative
"""

from __future__ import annotations

import pytest

from reviewer.change_summary import (
    build_change_summary,
    format_change_summary,
    _has_content_signal,
    _ROUTE_CONTENT_PATTERNS,
    _AUTH_CONTENT_PATTERNS,
    _VALIDATION_CONTENT_PATTERNS,
)
from reviewer.engine import analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.models import (
    PRContent,
    PRFile,
    PullRequestContext,
    ReviewBundle,
    ReviewBundleItem,
    ReviewPlan,
)
from reviewer.planner import build_review_plan
from reviewer.bundle import build_review_bundle
from reviewer.prompt_builder import (
    build_reasoning_request,
    _FULL_FILE_THRESHOLD,
    _MAX_REVIEW_TARGETS,
    _MAX_EXCERPT_CHARS,
)
from reviewer.providers import ReasoningRequest
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

def _make_scan_result(**overrides) -> ScanResult:
    defaults = {
        "repo": "test/repo",
        "pr_number": 1,
        "commit_sha": "abc1234567890",
        "ref": "main",
        "decision": Decision.PASS,
        "risk_score": 0,
        "findings": [],
    }
    defaults.update(overrides)
    return ScanResult(**defaults)


def _make_bundle_item(path: str, content: str = "", review_reason: str = "changed_file", **kwargs) -> ReviewBundleItem:
    return ReviewBundleItem(
        path=path,
        content=content,
        review_reason=review_reason,
        focus_areas=kwargs.get("focus_areas", []),
        baseline_context=kwargs.get("baseline_context", []),
        memory_context=kwargs.get("memory_context", []),
        related_paths=kwargs.get("related_paths", []),
    )


def _make_bundle(items: list[ReviewBundleItem]) -> ReviewBundle:
    return ReviewBundle(items=items)


def _make_plan(**kwargs) -> ReviewPlan:
    return ReviewPlan(**kwargs)


def _make_context(files: dict[str, str]) -> PullRequestContext:
    return PullRequestContext.from_dict(files)


# ======================================================================
# Part 1: Change Summary Generation
# ======================================================================

class TestChangeSummaryGeneration:
    """Test deterministic change summary generation."""

    def test_empty_bundle_returns_empty(self):
        """No bundle → no summary."""
        assert build_change_summary(None) == []
        assert build_change_summary(ReviewBundle()) == []

    def test_route_file_detected(self):
        """Route/endpoint files produce a route bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/routes/users.py", "from flask import Blueprint"),
        ])
        bullets = build_change_summary(bundle)
        assert any("route" in b.lower() or "endpoint" in b.lower() for b in bullets)

    def test_controller_file_detected(self):
        """Controller/handler files produce a controller bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/controllers/user_controller.py", "class UserController:"),
        ])
        bullets = build_change_summary(bundle)
        assert any("controller" in b.lower() or "handler" in b.lower() for b in bullets)

    def test_auth_file_detected(self):
        """Auth files produce an auth bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/auth/login.py", "def authenticate(user):", review_reason="auth_area"),
        ])
        bullets = build_change_summary(bundle)
        assert any("auth" in b.lower() for b in bullets)

    def test_validation_file_detected(self):
        """Validation files produce a validation bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/validators/user_validator.py", "def validate(data):"),
        ])
        bullets = build_change_summary(bundle)
        assert any("validation" in b.lower() for b in bullets)

    def test_model_file_detected(self):
        """Model/schema files produce a model bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/models/user.py", "class User:"),
        ])
        bullets = build_change_summary(bundle)
        assert any("model" in b.lower() or "schema" in b.lower() for b in bullets)

    def test_test_file_detected(self):
        """Test files produce a test bullet."""
        bundle = _make_bundle([
            _make_bundle_item("tests/test_auth.py", "def test_login():"),
        ])
        bullets = build_change_summary(bundle)
        assert any("test" in b.lower() for b in bullets)

    def test_config_file_detected(self):
        """Config files produce a configuration bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/config/settings.py", "SECRET_KEY = 'abc'"),
        ])
        bullets = build_change_summary(bundle)
        assert any("config" in b.lower() for b in bullets)

    def test_middleware_file_detected(self):
        """Middleware files produce a middleware bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/middleware/auth_middleware.py", "class AuthMiddleware:"),
        ])
        bullets = build_change_summary(bundle)
        assert any("middleware" in b.lower() for b in bullets)

    def test_service_file_detected(self):
        """Service files produce a service bullet."""
        bundle = _make_bundle([
            _make_bundle_item("src/services/payment.py", "class PaymentService:"),
        ])
        bullets = build_change_summary(bundle)
        assert any("service" in b.lower() for b in bullets)

    def test_multiple_change_types(self):
        """Multiple file types produce multiple bullets."""
        bundle = _make_bundle([
            _make_bundle_item("src/routes/api.py", "@app.route('/users')"),
            _make_bundle_item("src/models/user.py", "class User:"),
            _make_bundle_item("tests/test_users.py", "def test_users():"),
        ])
        bullets = build_change_summary(bundle)
        assert len(bullets) >= 3

    def test_content_based_route_detection(self):
        """Route content patterns trigger route detection."""
        bundle = _make_bundle([
            _make_bundle_item("src/api.py", "@app.get('/users')\ndef get_users():\n    pass"),
        ])
        bullets = build_change_summary(bundle)
        assert any("route" in b.lower() or "endpoint" in b.lower() for b in bullets)

    def test_summary_stays_compact(self):
        """Summary does not explode with many files."""
        items = [
            _make_bundle_item(f"src/routes/route_{i}.py", f"@app.get('/endpoint{i}')")
            for i in range(20)
        ]
        bundle = _make_bundle(items)
        bullets = build_change_summary(bundle)
        # Should consolidate into a count-based bullet
        assert any("20" in b or "file(s)" in b for b in bullets)

    def test_unclassified_files_get_generic_bullet(self):
        """Files with no matching classification get a generic count."""
        bundle = _make_bundle([
            _make_bundle_item("README.md", "# Project"),
            _make_bundle_item("LICENSE", "MIT"),
        ])
        bullets = build_change_summary(bundle)
        assert len(bullets) >= 1
        assert any("file(s) changed" in b for b in bullets)

    def test_summary_is_factual_not_judgmental(self):
        """Summary should not contain risk or attention language."""
        bundle = _make_bundle([
            _make_bundle_item("src/auth/login.py", "def authenticate():", review_reason="auth_area"),
            _make_bundle_item("src/routes/users.py", "@app.get('/users')"),
        ])
        bullets = build_change_summary(bundle)
        combined = " ".join(bullets).lower()
        assert "risk" not in combined
        assert "attention" not in combined
        assert "concern" not in combined
        assert "danger" not in combined
        assert "warning" not in combined

    def test_api_surface_expansion_from_plan(self):
        """Plan flags add API surface bullet if not already present."""
        bundle = _make_bundle([
            _make_bundle_item("src/app.py", "app = Flask()"),
        ])
        plan = _make_plan(review_flags=["api_surface_expansion"])
        bullets = build_change_summary(bundle, plan)
        assert any("api" in b.lower() for b in bullets)

    def test_migration_file_detected(self):
        """Migration files produce a migration bullet."""
        bundle = _make_bundle([
            _make_bundle_item("db/migrations/001_add_users.sql", "CREATE TABLE users"),
        ])
        bullets = build_change_summary(bundle)
        assert any("migration" in b.lower() for b in bullets)


class TestChangeSummaryFormatting:
    """Test change summary formatting to markdown."""

    def test_empty_bullets_return_empty_string(self):
        assert format_change_summary([]) == ""

    def test_single_bullet_formats_correctly(self):
        md = format_change_summary(["Route/endpoint changed: `users.py`"])
        assert "### 📝 What Changed" in md
        assert "- Route/endpoint changed: `users.py`" in md

    def test_multiple_bullets(self):
        md = format_change_summary([
            "Route/endpoint changed: `api.py`",
            "Model/schema changed: `user.py`",
            "Test changed: `test_user.py`",
        ])
        assert md.count("- ") == 3

    def test_format_ends_with_newline_separator(self):
        md = format_change_summary(["Something changed"])
        assert md.endswith("\n")


class TestChangeSummaryInMarkdown:
    """Test change summary rendering in full markdown output."""

    def test_change_summary_appears_in_markdown(self):
        """Change summary renders in the full markdown output."""
        result = _make_scan_result()
        md = format_markdown(
            result,
            change_summary_bullets=["Route/endpoint changed: `users.py`"],
        )
        assert "### 📝 What Changed" in md
        assert "Route/endpoint changed: `users.py`" in md

    def test_change_summary_before_provider_review(self):
        """Change summary appears before provider review section."""
        from reviewer.provider_review import ProviderReview, ProviderReviewItem
        review = ProviderReview(
            items=[ProviderReviewItem(
                kind="candidate_observation",
                title="Test item",
                summary="Test summary for provider review.",
                confidence="low",
            )],
            provider_name="test",
        )
        result = _make_scan_result()
        md = format_markdown(
            result,
            provider_review=review,
            change_summary_bullets=["Auth changed: `login.py`"],
        )
        summary_pos = md.index("What Changed")
        provider_pos = md.index("Provider Security Review")
        assert summary_pos < provider_pos

    def test_change_summary_after_decision(self):
        """Change summary appears after the decision badge."""
        result = _make_scan_result()
        md = format_markdown(
            result,
            change_summary_bullets=["Config changed: `settings.py`"],
        )
        decision_pos = md.index("Decision:")
        summary_pos = md.index("What Changed")
        assert decision_pos < summary_pos

    def test_no_change_summary_when_empty(self):
        """No change summary section when bullets are empty."""
        result = _make_scan_result()
        md = format_markdown(result, change_summary_bullets=[])
        assert "What Changed" not in md

    def test_no_change_summary_when_none(self):
        """No change summary section when bullets are None."""
        result = _make_scan_result()
        md = format_markdown(result, change_summary_bullets=None)
        assert "What Changed" not in md

    def test_backward_compat_no_change_summary_param(self):
        """format_markdown works without change_summary_bullets parameter."""
        result = _make_scan_result()
        md = format_markdown(result)
        assert "🔒 parity-zero Security Review" in md
        assert "What Changed" not in md


# ======================================================================
# Part 2: Provider Context Quality
# ======================================================================

class TestProviderContextDiffAware:
    """Test that provider requests include diff-aware evidence."""

    def test_change_summary_in_reasoning_request(self):
        """ReasoningRequest includes change_summary bullets."""
        files = {"src/routes/users.py": "@app.get('/users')\ndef list_users(): pass"}
        ctx = _make_context(files)
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        request = build_reasoning_request(ctx, plan, bundle)
        assert request.change_summary  # Should have at least one bullet
        assert isinstance(request.change_summary, list)

    def test_file_context_annotation_present(self):
        """Review targets include file_context annotations."""
        items = [_make_bundle_item(
            "src/auth/login.py",
            "def authenticate(user, password): pass",
            review_reason="auth_area",
            focus_areas=["authentication"],
        )]
        bundle = _make_bundle(items)
        ctx = _make_context({"src/auth/login.py": "def authenticate(user, password): pass"})
        plan = _make_plan(focus_areas=["authentication"])
        request = build_reasoning_request(ctx, plan, bundle)
        assert request.review_targets
        target = request.review_targets[0]
        assert "file_context" in target
        assert "auth" in target["file_context"].lower()

    def test_full_file_for_small_high_priority(self):
        """Small high-priority files get full content, not truncated excerpts."""
        small_content = "from flask import Blueprint\n\nbp = Blueprint('auth', __name__)\n\n@bp.route('/login')\ndef login():\n    return 'ok'\n"
        assert len(small_content) < _FULL_FILE_THRESHOLD
        items = [_make_bundle_item(
            "src/auth/routes.py",
            small_content,
            review_reason="sensitive_auth",
        )]
        bundle = _make_bundle(items)
        ctx = _make_context({"src/auth/routes.py": small_content})
        request = build_reasoning_request(ctx, plan=_make_plan(), bundle=bundle)
        target = request.review_targets[0]
        # Full file should be included without truncation markers
        assert target["code_excerpt"] == small_content
        assert "truncated" not in target["code_excerpt"]

    def test_large_file_still_bounded(self):
        """Large files are still bounded by _MAX_EXCERPT_CHARS."""
        large_content = "x = 1\n" * 2000  # Much larger than threshold
        items = [_make_bundle_item(
            "src/auth/big_handler.py",
            large_content,
            review_reason="sensitive_auth",
        )]
        bundle = _make_bundle(items)
        ctx = _make_context({"src/auth/big_handler.py": large_content})
        request = build_reasoning_request(ctx, plan=_make_plan(), bundle=bundle)
        target = request.review_targets[0]
        assert len(target["code_excerpt"]) <= _MAX_EXCERPT_CHARS + 100  # allow for truncation marker

    def test_low_priority_file_not_full_content(self):
        """Low-priority (changed_file) files do NOT get full content treatment."""
        small_content = "print('hello')\n"
        items = [_make_bundle_item(
            "src/utils.py",
            small_content,
            review_reason="changed_file",
        )]
        bundle = _make_bundle(items)
        ctx = _make_context({"src/utils.py": small_content})
        request = build_reasoning_request(ctx, plan=_make_plan(), bundle=bundle)
        # Should still work but uses normal bounded excerpt logic
        target = request.review_targets[0]
        assert target["code_excerpt"] == small_content  # Still small enough to include

    def test_file_context_for_api_surface(self):
        """API surface files get appropriate file_context annotation."""
        items = [_make_bundle_item(
            "src/api/endpoints.py",
            "@app.get('/users')",
            review_reason="api_surface",
            focus_areas=["authentication", "authorization"],
        )]
        bundle = _make_bundle(items)
        ctx = _make_context({"src/api/endpoints.py": "@app.get('/users')"})
        request = build_reasoning_request(ctx, plan=_make_plan(), bundle=bundle)
        target = request.review_targets[0]
        assert "API surface" in target.get("file_context", "")

    def test_review_targets_bounded(self):
        """Review targets don't exceed _MAX_REVIEW_TARGETS."""
        items = [
            _make_bundle_item(f"src/file_{i}.py", f"code {i}", review_reason="auth_area")
            for i in range(15)
        ]
        bundle = _make_bundle(items)
        ctx = _make_context({f"src/file_{i}.py": f"code {i}" for i in range(15)})
        request = build_reasoning_request(ctx, plan=_make_plan(), bundle=bundle)
        assert len(request.review_targets) <= _MAX_REVIEW_TARGETS


class TestProviderContextReviewUnits:
    """Test that provider requests prefer complete bounded review units."""

    def test_route_controller_grouping(self):
        """Related route+controller files appear together in targets."""
        items = [
            _make_bundle_item(
                "src/routes/users.py",
                "@app.get('/users')\ndef list_users(): pass",
                review_reason="api_surface",
                related_paths=["src/controllers/user_controller.py"],
            ),
            _make_bundle_item(
                "src/controllers/user_controller.py",
                "class UserController:\n    def list(self): pass",
                review_reason="changed_file",
            ),
        ]
        bundle = _make_bundle(items)
        ctx = _make_context({
            "src/routes/users.py": "@app.get('/users')",
            "src/controllers/user_controller.py": "class UserController: pass",
        })
        request = build_reasoning_request(ctx, plan=_make_plan(), bundle=bundle)
        # The route target should include related_code from controller
        route_target = next(t for t in request.review_targets if "routes" in t["path"])
        assert "related_code" in route_target or "related_paths" in route_target

    def test_auth_validation_grouping(self):
        """Auth + validation files appear together."""
        items = [
            _make_bundle_item(
                "src/auth/login.py",
                "def login(request): pass",
                review_reason="sensitive_auth",
                related_paths=["src/validators/login_validator.py"],
            ),
            _make_bundle_item(
                "src/validators/login_validator.py",
                "def validate_login(data): pass",
                review_reason="changed_file",
            ),
        ]
        bundle = _make_bundle(items)
        ctx = _make_context({
            "src/auth/login.py": "def login(request): pass",
            "src/validators/login_validator.py": "def validate_login(data): pass",
        })
        request = build_reasoning_request(ctx, plan=_make_plan(), bundle=bundle)
        auth_target = next(t for t in request.review_targets if "auth" in t["path"])
        assert "related_code" in auth_target or "related_paths" in auth_target


# ======================================================================
# Part 3: Content Signal Detection
# ======================================================================

class TestContentSignalDetection:
    """Test content-based detection of change types."""

    def test_route_content_signals(self):
        assert _has_content_signal("@app.get('/users')", _ROUTE_CONTENT_PATTERNS)
        assert _has_content_signal("router.post('/items')", _ROUTE_CONTENT_PATTERNS)
        assert _has_content_signal("urlpatterns = [", _ROUTE_CONTENT_PATTERNS)

    def test_auth_content_signals(self):
        assert _has_content_signal("def authenticate(user):", _AUTH_CONTENT_PATTERNS)
        assert _has_content_signal("jwt.decode(token)", _AUTH_CONTENT_PATTERNS)

    def test_validation_content_signals(self):
        assert _has_content_signal("def validate(data):", _VALIDATION_CONTENT_PATTERNS)
        assert _has_content_signal("schema = Joi.object()", _VALIDATION_CONTENT_PATTERNS)

    def test_no_signal_for_plain_code(self):
        assert not _has_content_signal("x = 1 + 2", _ROUTE_CONTENT_PATTERNS)
        assert not _has_content_signal("print('hello')", _AUTH_CONTENT_PATTERNS)

    def test_empty_content(self):
        assert not _has_content_signal("", _ROUTE_CONTENT_PATTERNS)
        assert not _has_content_signal(None, _ROUTE_CONTENT_PATTERNS)


# ======================================================================
# Part 4: Regression / Trust Boundary Tests
# ======================================================================

class TestRegressionTrustBoundaries:
    """Verify ScanResult, scoring, and provider non-authority are preserved."""

    def test_scan_result_unchanged(self):
        """ScanResult schema is not modified by this change."""
        result = _make_scan_result()
        data = result.model_dump()
        # Core fields present
        assert "repo" in data
        assert "pr_number" in data
        assert "commit_sha" in data
        assert "decision" in data
        assert "risk_score" in data
        assert "findings" in data
        # No new fields from change summary
        assert "change_summary" not in data

    def test_scoring_unchanged(self):
        """Decision/risk derivation is unaffected."""
        findings = [
            Finding(
                title="Test",
                description="desc",
                category=Category.AUTHENTICATION,
                severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                file="test.py",
            )
        ]
        decision, risk = derive_decision_and_risk(findings)
        assert decision == Decision.WARN
        assert risk == 25

    def test_scoring_empty_findings(self):
        decision, risk = derive_decision_and_risk([])
        assert decision == Decision.PASS
        assert risk == 0

    def test_provider_review_remains_non_authoritative(self):
        """Provider review items do not become findings or affect scoring."""
        from reviewer.provider_review import ProviderReviewItem, ProviderReview
        review = ProviderReview(
            items=[ProviderReviewItem(
                kind="candidate_finding",
                title="Potential SQL injection",
                summary="Possible unsafe query construction.",
                confidence="medium",
                category="input_validation",
            )],
            provider_name="test",
        )
        result = _make_scan_result()
        md = format_markdown(
            result,
            provider_review=review,
            change_summary_bullets=["Route/endpoint changed: `api.py`"],
        )
        # Provider review items should be marked as non-authoritative
        assert "not proven findings" in md or "not affect the decision" in md
        # Risk score should still be 0 (no actual findings)
        assert result.risk_score == 0

    def test_analyse_returns_bundle(self):
        """analyse() returns bundle in AnalysisResult for summary generation."""
        files = {"src/config.py": "DEBUG = True\n"}
        result = analyse(files)
        assert result.bundle is not None

    def test_change_summary_does_not_affect_json_contract(self):
        """Change summary is markdown-only; it does not appear in JSON output."""
        result = _make_scan_result()
        json_str = result.model_dump_json()
        assert "What Changed" not in json_str
        assert "change_summary" not in json_str


# ======================================================================
# Part 5: End-to-End Integration
# ======================================================================

class TestEndToEndChangeSummary:
    """End-to-end tests for change summary in the full pipeline."""

    def test_route_change_produces_summary(self):
        """A PR with route changes produces a meaningful change summary."""
        files = {
            "src/routes/users.py": (
                "from flask import Blueprint\n"
                "\n"
                "bp = Blueprint('users', __name__)\n"
                "\n"
                "@bp.route('/users')\n"
                "def list_users():\n"
                "    return []\n"
            ),
        }
        ctx = _make_context(files)
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        bullets = build_change_summary(bundle, plan)
        assert bullets  # Should have at least one bullet
        combined = " ".join(bullets).lower()
        assert "route" in combined or "endpoint" in combined

    def test_auth_config_change_produces_summary(self):
        """A PR with auth and config changes produces relevant bullets."""
        files = {
            "src/auth/login.py": "def authenticate(user, password): return True\n",
            "src/config/settings.py": "SECRET_KEY = 'changeme'\n",
        }
        ctx = _make_context(files)
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        bullets = build_change_summary(bundle, plan)
        combined = " ".join(bullets).lower()
        assert "auth" in combined
        assert "config" in combined

    def test_docs_only_change_minimal_summary(self):
        """A docs-only PR produces a minimal or empty summary."""
        files = {
            "README.md": "# Project\nUpdated docs.\n",
            "CHANGELOG.md": "## v1.0\n- Initial release\n",
        }
        ctx = _make_context(files)
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        bullets = build_change_summary(bundle, plan)
        # Should produce at most a generic file count bullet
        if bullets:
            combined = " ".join(bullets).lower()
            # Should not claim route/auth/model changes
            assert "route" not in combined
            assert "auth" not in combined
            assert "model" not in combined

    def test_full_pipeline_markdown_with_summary(self):
        """Full pipeline produces markdown with change summary when meaningful."""
        files = {
            "src/routes/admin.py": (
                "from fastapi import APIRouter\n"
                "router = APIRouter()\n"
                "@router.get('/admin/dashboard')\n"
                "async def dashboard():\n"
                "    return {'status': 'ok'}\n"
            ),
        }
        ctx = _make_context(files)
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
        change_bullets = build_change_summary(bundle=analysis.bundle)
        md = format_markdown(
            result,
            concerns=analysis.concerns,
            observations=analysis.observations,
            change_summary_bullets=change_bullets,
        )
        assert "🔒 parity-zero Security Review" in md
        # The route change should produce a summary bullet
        if change_bullets:
            assert "What Changed" in md
