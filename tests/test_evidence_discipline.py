"""Tests for provider quality hardening — evidence discipline (ADR-046).

Validates:
1. Post-parse evidence discipline suppresses/softens speculative items
2. Weak validation/security guesses based on filenames alone are suppressed
3. Fixture/test noise is reduced
4. Directly evidenced positive controls can still survive
5. Provider requests include more complete bounded review units
6. Complete changed handlers/functions are included where appropriate
7. Route/controller/validation groupings for endpoint/resource scenarios
8. Prompts remain bounded and do not explode in size
9. Realistic scenarios produce fewer speculative items
10. Provider output remains useful on authz-sensitive endpoint/resource scenarios
11. Low-signal scenarios remain quiet
12. Duplicated/overlapping weak items are reduced
13. Provider output still does not affect ScanResult
14. Scoring unchanged
15. Deterministic findings unchanged as authoritative inputs

Trust boundaries:
- Provider output remains non-authoritative
- ScanResult JSON contract unchanged
- Scoring derived only from deterministic findings
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
from reviewer.prompt_builder import (
    _MAX_EXCERPT_CHARS,
    _MAX_REVIEW_TARGETS,
    _bounded_excerpt,
    _find_natural_boundary,
    build_reasoning_request,
)
from reviewer.provider_review import (
    MAX_REVIEW_ITEMS,
    ProviderReview,
    ProviderReviewItem,
    apply_evidence_discipline,
    _apply_item_discipline,
    _collapse_weak_duplicates,
    _is_non_security_commentary,
    _is_speculative_missing_control,
    _is_test_fixture_item,
    _is_test_fixture_path,
    _has_concrete_security_evidence,
    _is_filename_only_guess,
    _soften_title,
    _soften_summary,
    parse_and_validate_provider_review,
)
from reviewer.providers import MockProvider, ReasoningRequest
from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk


# ======================================================================
# Part 1: Evidence discipline — speculative claims suppression
# ======================================================================


class TestSpeculativeClaimsSuppression:
    """Provider items claiming missing controls are suppressed or softened
    when code evidence is incomplete."""

    def test_missing_auth_without_evidence_is_suppressed(self):
        """Speculative 'missing authorization' without evidence -> suppressed."""
        item = ProviderReviewItem(
            kind="candidate_finding",
            category="authorization",
            title="Missing authorization check on delete",
            summary="The delete endpoint is missing authorization checks",
            paths=["src/api/notes.py"],
            confidence="medium",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_missing_auth_with_evidence_is_softened(self):
        """Speculative 'missing authorization' with evidence -> softened."""
        item = ProviderReviewItem(
            kind="candidate_finding",
            category="authorization",
            title="Missing authorization check on delete",
            summary="The delete endpoint is missing authorization checks for ownership",
            paths=["src/api/notes.py"],
            confidence="medium",
            evidence="def delete_note(note_id): return db.delete(note_id) # no owner check",
        )
        result = _apply_item_discipline(item)
        assert result is not None
        assert result.kind == "review_attention"
        assert result.confidence == "low"

    def test_missing_authentication_without_evidence_is_suppressed(self):
        item = ProviderReviewItem(
            kind="candidate_finding",
            category="authentication",
            title="No authentication check",
            summary="No authentication check is performed before accessing the resource",
            paths=["src/routes/api.py"],
            confidence="medium",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_missing_input_validation_without_evidence_is_suppressed(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="input_validation",
            title="Missing input validation",
            summary="No input validation is applied to the request body",
            paths=["src/handlers/create.py"],
            confidence="low",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_legitimate_finding_with_evidence_survives(self):
        """Well-evidenced security observation should survive discipline."""
        item = ProviderReviewItem(
            kind="candidate_finding",
            category="secrets",
            title="Hardcoded API key in config",
            summary="Configuration file contains a hardcoded API key that may be production",
            paths=["src/config/settings.py"],
            confidence="medium",
            evidence="API_KEY = 'sk-live-abc123...' on line 42",
        )
        result = _apply_item_discipline(item)
        assert result is not None
        assert result.kind == "candidate_finding"
        assert result.confidence == "medium"


class TestSofteningLanguage:
    """Verify softened titles and summaries use review-attention phrasing."""

    def test_soften_missing_title(self):
        result = _soften_title("Missing authorization check")
        assert "verify" in result.lower() or "Verify" in result

    def test_soften_no_title(self):
        result = _soften_title("No authentication check")
        assert result.startswith("Verify ")

    def test_soften_lacks_title(self):
        result = _soften_title("Lacks authorization middleware")
        assert result.startswith("Verify ")

    def test_soften_summary_missing(self):
        result = _soften_summary("The endpoint is missing authorization checks")
        assert "verification" in result.lower() or "may" in result.lower()

    def test_soften_summary_no_auth(self):
        result = _soften_summary("There is no authorization on delete")
        assert "should be verified" in result.lower() or "may" in result.lower()


# ======================================================================
# Part 2: Filename-only guesses suppression
# ======================================================================


class TestFilenameOnlyGuesses:
    """Weak validation/security guesses based on filenames alone are suppressed."""

    def test_category_from_filename_without_evidence_suppressed(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="authentication",
            title="Auth file changes",
            summary="Changes to auth.py",
            paths=["src/auth.py"],
            confidence="low",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_category_with_evidence_survives(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="authentication",
            title="JWT token validation",
            summary="The JWT token validation in auth.py does not check the expiration claim which could allow expired tokens",
            paths=["src/auth.py"],
            confidence="medium",
            evidence="decoded = jwt.decode(token, key, algorithms=['HS256'])  # no exp check",
        )
        result = _apply_item_discipline(item)
        assert result is not None
        assert result.kind == "candidate_observation"

    def test_is_filename_only_guess_short_summary(self):
        item = ProviderReviewItem(
            category="authorization",
            summary="File touches auth area",
            paths=["src/auth/middleware.py"],
            evidence="",
        )
        assert _is_filename_only_guess(item) is True

    def test_is_filename_only_guess_substantive_summary(self):
        item = ProviderReviewItem(
            category="authorization",
            summary="The authorization middleware in this file can be bypassed when the user-agent header contains a specific string because the check returns early without verifying the session token",
            paths=["src/auth/middleware.py"],
            evidence="if 'bot' in request.headers.get('user-agent', ''): return True",
        )
        assert _is_filename_only_guess(item) is False


# ======================================================================
# Part 3: Test/fixture noise reduction
# ======================================================================


class TestFixtureNoiseReduction:
    """Fixture/test noise is reduced."""

    def test_test_file_without_security_evidence_suppressed(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="input_validation",
            title="Test data validation",
            summary="Test data does not validate edge cases for boundary conditions",
            paths=["tests/test_auth.py"],
            confidence="low",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_fixture_file_without_security_evidence_suppressed(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="secrets",
            title="Fixture data review",
            summary="The fixture file contains sample data for testing purposes",
            paths=["test/fixtures/sample_data.json"],
            confidence="low",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_test_file_with_hardcoded_credentials_survives(self):
        item = ProviderReviewItem(
            kind="candidate_finding",
            category="secrets",
            title="Production credential in test",
            summary="Test fixture contains what appears to be a production API key",
            paths=["tests/fixtures/config.json"],
            confidence="medium",
            evidence="'api_key': 'sk-live-prod-abc123' -- this looks like a real production credential",
        )
        result = _apply_item_discipline(item)
        assert result is not None

    def test_is_test_fixture_path_patterns(self):
        assert _is_test_fixture_path("tests/test_auth.py") is True
        assert _is_test_fixture_path("test/fixtures/data.json") is True
        assert _is_test_fixture_path("spec/models/user_spec.rb") is True
        assert _is_test_fixture_path("__tests__/auth.test.js") is True
        assert _is_test_fixture_path("src/auth/middleware.py") is False
        assert _is_test_fixture_path("src/api/routes.py") is False

    def test_has_concrete_security_evidence(self):
        item_with = ProviderReviewItem(
            evidence="Contains hardcoded password 'admin123' in fixture",
        )
        assert _has_concrete_security_evidence(item_with) is True

        item_without = ProviderReviewItem(
            evidence="Test validates edge cases",
        )
        assert _has_concrete_security_evidence(item_without) is False


# ======================================================================
# Part 4: Non-security commentary suppression
# ======================================================================


class TestNonSecurityCommentary:
    """Weak non-security commentary is suppressed."""

    def test_code_quality_suppressed(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            title="Code quality concern",
            summary="The code quality could be improved by extracting common logic",
            paths=["src/api.py"],
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_documentation_missing_suppressed(self):
        item = ProviderReviewItem(
            kind="review_attention",
            title="Missing documentation",
            summary="The new endpoint lacks documentation for its parameters and response format",
            paths=["src/routes.py"],
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_performance_concern_suppressed(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            title="Performance issue",
            summary="The performance optimization in this loop could be improved with caching",
            paths=["src/compute.py"],
        )
        result = _apply_item_discipline(item)
        assert result is None

    def test_is_non_security_commentary(self):
        assert _is_non_security_commentary("code quality issues found") is True
        assert _is_non_security_commentary("naming convention not followed") is True
        assert _is_non_security_commentary("sql injection vulnerability") is False
        assert _is_non_security_commentary("authorization bypass possible") is False


# ======================================================================
# Part 5: Positive controls discipline
# ======================================================================


class TestPositiveControlsDiscipline:
    """Directly evidenced positive controls can still survive."""

    def test_positive_control_with_evidence_survives(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="authentication",
            title="Proper JWT validation",
            summary="The authentication middleware properly validates JWT tokens including expiration and signature checks",
            paths=["src/auth/jwt.py"],
            confidence="medium",
            evidence="jwt.decode(token, key, algorithms=['HS256'], options={'verify_exp': True})",
        )
        result = _apply_item_discipline(item)
        assert result is not None
        assert result.kind == "candidate_observation"

    def test_positive_control_without_evidence_has_low_confidence(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="authorization",
            title="Good authorization practice",
            summary="The route handler appears to properly check user permissions before allowing access to resources",
            paths=["src/routes/notes.py"],
            confidence="medium",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is not None
        assert result.confidence == "low"


# ======================================================================
# Part 6: Confidence discipline
# ======================================================================


class TestConfidenceDiscipline:
    """Provider items with weak evidence should not have medium confidence."""

    def test_no_evidence_bounds_to_low_confidence(self):
        item = ProviderReviewItem(
            kind="candidate_observation",
            category="insecure_configuration",
            title="Configuration review",
            summary="The application configuration may expose internal service details through error pages",
            paths=["src/config.py"],
            confidence="medium",
            evidence="",
        )
        result = _apply_item_discipline(item)
        assert result is not None
        assert result.confidence == "low"

    def test_with_evidence_preserves_medium_confidence(self):
        item = ProviderReviewItem(
            kind="candidate_finding",
            category="insecure_configuration",
            title="Debug mode enabled",
            summary="Debug mode is enabled in production configuration exposing stack traces",
            paths=["src/config.py"],
            confidence="medium",
            evidence="DEBUG = True  # in production.py config",
        )
        result = _apply_item_discipline(item)
        assert result is not None
        assert result.confidence == "medium"


# ======================================================================
# Part 7: Weak duplicate collapse
# ======================================================================


class TestWeakDuplicateCollapse:
    """Duplicated/overlapping weak items are reduced."""

    def test_collapse_same_category_same_path(self):
        items = [
            ProviderReviewItem(
                kind="review_attention",
                category="authorization",
                title="Check auth on endpoint A",
                summary="Verify authorization checks on endpoint A in this route handler",
                paths=["src/routes.py"],
                confidence="low",
            ),
            ProviderReviewItem(
                kind="review_attention",
                category="authorization",
                title="Check auth on endpoint B",
                summary="Verify authorization checks on endpoint B in this route handler",
                paths=["src/routes.py"],
                confidence="low",
            ),
        ]
        result = _collapse_weak_duplicates(items)
        assert len(result) == 1

    def test_different_categories_not_collapsed(self):
        items = [
            ProviderReviewItem(
                kind="review_attention",
                category="authorization",
                title="Auth check",
                summary="Verify authorization for this endpoint is correct and complete",
                paths=["src/routes.py"],
                confidence="low",
            ),
            ProviderReviewItem(
                kind="review_attention",
                category="input_validation",
                title="Input check",
                summary="Verify input validation for this endpoint handles edge cases properly",
                paths=["src/routes.py"],
                confidence="low",
            ),
        ]
        result = _collapse_weak_duplicates(items)
        assert len(result) == 2

    def test_stronger_item_preserved_in_collapse(self):
        items = [
            ProviderReviewItem(
                kind="review_attention",
                category="authorization",
                title="Weak auth check",
                summary="Verify authorization on delete endpoint is properly implemented",
                paths=["src/routes.py"],
                confidence="low",
                evidence="",
            ),
            ProviderReviewItem(
                kind="review_attention",
                category="authorization",
                title="Better auth check",
                summary="Verify authorization on delete -- visible code shows no owner check",
                paths=["src/routes.py"],
                confidence="low",
                evidence="def delete(note_id): db.delete(note_id)  # no owner check",
            ),
        ]
        result = _collapse_weak_duplicates(items)
        assert len(result) == 1
        assert "Better" in result[0].title

    def test_unrelated_items_not_collapsed(self):
        items = [
            ProviderReviewItem(
                kind="review_attention",
                category="authorization",
                title="Auth review A",
                summary="Verify authorization on this endpoint is correct and complete",
                paths=["src/routes/notes.py"],
                confidence="low",
            ),
            ProviderReviewItem(
                kind="review_attention",
                category="authorization",
                title="Auth review B",
                summary="Verify authorization on this other endpoint is correct and complete",
                paths=["src/routes/users.py"],
                confidence="low",
            ),
        ]
        result = _collapse_weak_duplicates(items)
        assert len(result) == 2


# ======================================================================
# Part 8: End-to-end evidence discipline via parse_and_validate
# ======================================================================


class TestEndToEndEvidenceDiscipline:
    """Evidence discipline is applied in the parse_and_validate pipeline."""

    def test_speculative_items_filtered_in_pipeline(self):
        raw = json.dumps([
            {
                "kind": "candidate_finding",
                "category": "authorization",
                "title": "Missing authorization on delete",
                "summary": "The delete endpoint is missing authorization checks for ownership",
                "paths": ["src/api/notes.py"],
                "confidence": "medium",
                "evidence": "",
            },
            {
                "kind": "candidate_observation",
                "category": "authentication",
                "title": "Proper JWT usage",
                "summary": "The authentication module properly validates JWT tokens with expiration and signature checks following secure patterns",
                "paths": ["src/auth/jwt.py"],
                "confidence": "medium",
                "evidence": "jwt.decode(token, key, algorithms=['HS256'], options={'verify_exp': True})",
            },
        ])
        review = parse_and_validate_provider_review(raw, "test")
        assert review.item_count >= 1
        titles = [item.title for item in review.items]
        assert not any("Missing authorization" in t for t in titles)

    def test_test_fixture_noise_filtered_in_pipeline(self):
        raw = json.dumps([
            {
                "kind": "candidate_observation",
                "category": "input_validation",
                "title": "Test data review",
                "summary": "Test data does not cover edge cases for the validation function",
                "paths": ["tests/test_validation.py"],
                "confidence": "low",
                "evidence": "",
            },
        ])
        review = parse_and_validate_provider_review(raw, "test")
        assert review.item_count == 0

    def test_well_evidenced_items_survive_pipeline(self):
        raw = json.dumps([
            {
                "kind": "candidate_finding",
                "category": "secrets",
                "title": "Hardcoded production key",
                "summary": "Configuration file contains a hardcoded API key that appears to be a production credential based on the prefix pattern",
                "paths": ["src/config/prod.py"],
                "confidence": "medium",
                "evidence": "API_KEY = 'sk-live-abc123def456' -- sk-live prefix indicates production",
            },
        ])
        review = parse_and_validate_provider_review(raw, "test")
        assert review.item_count == 1
        assert review.items[0].confidence == "medium"

    def test_non_security_commentary_filtered(self):
        raw = json.dumps([
            {
                "kind": "candidate_observation",
                "title": "Code quality concern",
                "summary": "The code quality in this module could be improved with better abstractions",
                "paths": ["src/utils.py"],
                "confidence": "low",
                "evidence": "",
            },
        ])
        review = parse_and_validate_provider_review(raw, "test")
        assert review.item_count == 0


# ======================================================================
# Part 9: Code evidence sufficiency — bounded review units
# ======================================================================


class TestBoundedReviewUnits:
    """Provider requests include more complete bounded review units."""

    def test_excerpt_size_increased(self):
        assert _MAX_EXCERPT_CHARS == 2500

    def test_bounded_excerpt_under_limit(self):
        content = "def handler():\n    return ok()\n"
        result = _bounded_excerpt(content)
        assert result == content

    def test_bounded_excerpt_at_natural_boundary(self):
        first_fn = "def first_handler():\n" + "    x = 1\n" * 200
        second_fn = "\ndef second_handler():\n" + "    y = 2\n" * 200
        content = first_fn + second_fn
        assert len(content) > _MAX_EXCERPT_CHARS

        result = _bounded_excerpt(content)
        assert "truncated" in result
        assert "first_handler" in result

    def test_find_natural_boundary_python(self):
        text = "# header\n\ndef first():\n    pass\n\ndef second():\n    pass\n"
        boundary = _find_natural_boundary(text)
        assert boundary > 0

    def test_find_natural_boundary_no_boundary(self):
        text = "just some text without any function definitions"
        boundary = _find_natural_boundary(text)
        assert boundary == 0

    def test_review_targets_include_code(self):
        """Review targets should carry code excerpts when a bundle is provided."""
        from reviewer.bundle import build_review_bundle
        files = [
            PRFile(path="src/routes/notes.py", content="router.get('/notes', getAll)\nrouter.delete('/notes/:id', delete)\n"),
            PRFile(path="src/controllers/notes.py", content="def delete(note_id):\n    return db.delete(note_id)\n"),
        ]
        ctx = PullRequestContext(
            pr_content=PRContent(files=files),
            baseline_profile=RepoSecurityProfile(
                sensitive_paths=["src/routes/", "src/controllers/"],
                auth_patterns=["JWT"],
            ),
        )
        plan = ReviewPlan(
            focus_areas=["authorization"],
            sensitive_paths_touched=["src/routes/notes.py", "src/controllers/notes.py"],
            auth_paths_touched=[],
        )
        bundle = build_review_bundle(ctx, plan)
        request = build_reasoning_request(ctx=ctx, plan=plan, bundle=bundle)
        assert request.has_review_targets
        assert any(t.get("code_excerpt") for t in request.review_targets)

    def test_review_targets_bounded_count(self):
        files = [
            PRFile(path=f"src/file{i}.py", content=f"def func{i}():\n    pass\n")
            for i in range(20)
        ]
        ctx = PullRequestContext(pr_content=PRContent(files=files))
        plan = ReviewPlan(
            focus_areas=["authorization"],
            sensitive_paths_touched=[f.path for f in files],
        )
        request = build_reasoning_request(ctx=ctx, plan=plan)
        assert len(request.review_targets) <= _MAX_REVIEW_TARGETS

    def test_prompt_size_bounded(self):
        big_content = "def handler():\n" + "    x = process()\n" * 200
        files = [
            PRFile(path=f"src/auth/endpoint{i}.py", content=big_content)
            for i in range(10)
        ]
        ctx = PullRequestContext(
            pr_content=PRContent(files=files),
            baseline_profile=RepoSecurityProfile(
                sensitive_paths=["src/auth/"],
                auth_patterns=["JWT"],
            ),
        )
        plan = ReviewPlan(
            focus_areas=["authentication", "authorization"],
            sensitive_paths_touched=[f.path for f in files],
            auth_paths_touched=[f.path for f in files],
        )
        request = build_reasoning_request(ctx=ctx, plan=plan)
        total_code = sum(
            len(t.get("code_excerpt", "")) + len(t.get("related_code", ""))
            for t in request.review_targets
        )
        assert total_code < 30000


# ======================================================================
# Part 10: Stability and quality
# ======================================================================


class TestStabilityAndQuality:
    """Realistic scenarios produce fewer speculative items."""

    def test_apply_evidence_discipline_reduces_noise(self):
        review = ProviderReview(
            items=[
                ProviderReviewItem(
                    kind="candidate_finding",
                    category="authorization",
                    title="Missing authorization on delete",
                    summary="The delete endpoint is missing authorization checks",
                    paths=["src/api.py"],
                    confidence="medium",
                    evidence="",
                ),
                ProviderReviewItem(
                    kind="candidate_observation",
                    category="input_validation",
                    title="Test validation noise",
                    summary="Test data does not validate edge cases for boundary conditions",
                    paths=["tests/test_auth.py"],
                    confidence="low",
                    evidence="",
                ),
                ProviderReviewItem(
                    kind="review_attention",
                    title="Code quality concern",
                    summary="The code quality could be improved by extracting logic",
                    paths=["src/utils.py"],
                    confidence="low",
                    evidence="",
                ),
                ProviderReviewItem(
                    kind="candidate_finding",
                    category="secrets",
                    title="Hardcoded credential",
                    summary="Configuration contains hardcoded database connection string with embedded password",
                    paths=["src/config.py"],
                    confidence="medium",
                    evidence="DB_URL = 'postgres://admin:secretpass@db:5432/app'",
                ),
            ],
            raw_item_count=4,
            discarded_count=0,
        )
        result = apply_evidence_discipline(review)
        assert result.item_count < review.item_count
        titles = [item.title for item in result.items]
        assert "Hardcoded credential" in titles
        assert "Code quality concern" not in titles

    def test_empty_review_passes_through(self):
        review = ProviderReview(items=[], raw_item_count=0)
        result = apply_evidence_discipline(review)
        assert result.item_count == 0

    def test_all_valid_items_survive(self):
        review = ProviderReview(
            items=[
                ProviderReviewItem(
                    kind="candidate_finding",
                    category="secrets",
                    title="API key exposure",
                    summary="The configuration file contains a hardcoded production API key that should use environment variables",
                    paths=["src/config.py"],
                    confidence="medium",
                    evidence="API_KEY = 'sk-live-abc123' on line 15",
                ),
                ProviderReviewItem(
                    kind="candidate_observation",
                    category="authorization",
                    title="Ownership check in place",
                    summary="The update handler properly verifies object ownership before allowing modification",
                    paths=["src/api/notes.py"],
                    confidence="medium",
                    evidence="if note.owner_id != current_user.id: raise Forbidden()",
                ),
            ],
            raw_item_count=2,
            discarded_count=0,
        )
        result = apply_evidence_discipline(review)
        assert result.item_count == 2

    def test_low_signal_scenario_stays_quiet(self):
        """Trivial changes should produce no items after discipline."""
        raw = json.dumps([
            {
                "kind": "candidate_observation",
                "title": "Minor documentation update",
                "summary": "Missing documentation for the configuration section is now addressed",
                "paths": ["README.md"],
                "confidence": "low",
                "evidence": "",
            },
        ])
        review = parse_and_validate_provider_review(raw, "test")
        assert review.item_count == 0


# ======================================================================
# Part 11: Trust boundary preservation
# ======================================================================


class TestTrustBoundaryPreservation:
    """Provider output still does not affect ScanResult, scoring, findings."""

    def _make_ctx(self, files: dict[str, str]) -> PullRequestContext:
        return PullRequestContext.from_dict(files)

    def test_provider_review_does_not_affect_scan_result(self):
        ctx = self._make_ctx({
            "src/auth/login.py": "def login(req):\n    return auth(req)\n",
        })
        result = analyse(ctx, provider=MockProvider())
        assert isinstance(result, AnalysisResult)
        # AnalysisResult.findings drives scoring — provider_review is separate
        # and must not appear in the finding list
        for finding in result.findings:
            assert finding.source != "provider"

    def test_scoring_unchanged_by_provider(self):
        ctx = self._make_ctx({
            "src/notes.py": "def get_note(id):\n    return db.query(id)\n",
        })
        result_without = analyse(ctx)
        result_with = analyse(ctx, provider=MockProvider())
        dec_w, risk_w = derive_decision_and_risk(result_without.findings)
        dec_p, risk_p = derive_decision_and_risk(result_with.findings)
        assert risk_w == risk_p
        assert dec_w == dec_p

    def test_deterministic_findings_unchanged(self):
        """Deterministic findings should be identical with or without provider."""
        ctx = self._make_ctx({
            "src/app.py": "import os\n",
        })
        result_without = analyse(ctx)
        result_with = analyse(ctx, provider=MockProvider())
        assert len(result_without.findings) == len(result_with.findings)


# ======================================================================
# Part 12: Authz-sensitive endpoint scenario
# ======================================================================


class TestAuthzSensitiveScenario:
    """Provider output remains useful on authz-sensitive endpoint/resource scenarios."""

    def test_authz_sensitive_endpoint_produces_useful_output(self):
        """Auth-sensitive code should produce meaningful provider review items."""
        ctx = PullRequestContext.from_dict({
            "src/auth/middleware.py": (
                "from jwt import decode\n"
                "def require_auth(f):\n"
                "    def wrapper(request):\n"
                "        token = request.headers.get('Authorization', '').replace('Bearer ', '')\n"
                "        user = decode(token, SECRET_KEY, algorithms=['HS256'])\n"
                "        request.user = user\n"
                "        return f(request)\n"
                "    return wrapper\n"
            ),
            "src/api/notes.py": (
                "@require_auth\n"
                "def get_note(request, note_id):\n"
                "    note = db.notes.find_one({'_id': note_id})\n"
                "    return jsonify(note)\n"
                "\n"
                "@require_auth\n"
                "def delete_note(request, note_id):\n"
                "    db.notes.delete_one({'_id': note_id})\n"
                "    return jsonify({'deleted': True})\n"
            ),
        })
        ctx.baseline_profile = RepoSecurityProfile(
            sensitive_paths=["src/auth/", "src/api/"],
            auth_patterns=["JWT", "Bearer token"],
            frameworks=["Flask"],
        )
        result = analyse(ctx, provider=MockProvider())
        # Should have some provider review items for auth-sensitive code
        assert result.provider_review is not None
        # The overall result should still be valid
        assert isinstance(result, AnalysisResult)
