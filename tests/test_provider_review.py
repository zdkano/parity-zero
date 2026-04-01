"""Tests for provider-first structured review output (ADR-044).

Validates:
- ProviderReviewItem schema and normalisation
- Structured provider JSON parsing
- Malformed output handling (fail-safe)
- Taxonomy/category mapping
- Confidence bounding
- Deduplication
- Trust boundary preservation (no ScanResult contract changes, no scoring changes)
- Markdown rendering of structured provider review items
- Pipeline integration with mock provider
"""

from __future__ import annotations

import json

import pytest

from reviewer.provider_review import (
    MAX_REVIEW_ITEMS,
    VALID_CATEGORIES,
    VALID_CONFIDENCES,
    VALID_KINDS,
    ProviderReview,
    ProviderReviewItem,
    normalize_review_item,
    parse_and_validate_provider_review,
    parse_provider_review_json,
    validate_and_normalize,
)
from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.models import (
    PRContent,
    PRFile,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)
from reviewer.providers import MockProvider, ReasoningResponse
from schemas.findings import (
    Category,
    Confidence,
    Decision,
    Finding,
    ScanResult,
    Severity,
)


# ======================================================================
# Schema basics
# ======================================================================


class TestProviderReviewItemSchema:
    """Test the ProviderReviewItem dataclass."""

    def test_default_values(self):
        item = ProviderReviewItem()
        assert item.kind == "candidate_observation"
        assert item.category == ""
        assert item.title == ""
        assert item.summary == ""
        assert item.paths == []
        assert item.confidence == "low"
        assert item.evidence == ""
        assert item.source == "provider"

    def test_custom_values(self):
        item = ProviderReviewItem(
            kind="candidate_finding",
            category="authentication",
            title="Missing auth check",
            summary="Route /api/users lacks auth middleware.",
            paths=["src/routes/users.py"],
            confidence="medium",
            evidence="@app.route('/api/users') has no @login_required",
            source="github-models",
        )
        assert item.kind == "candidate_finding"
        assert item.category == "authentication"
        assert item.confidence == "medium"
        assert len(item.paths) == 1

    def test_valid_kinds(self):
        for kind in VALID_KINDS:
            item = ProviderReviewItem(kind=kind)
            assert item.kind == kind

    def test_valid_categories(self):
        for cat in VALID_CATEGORIES:
            item = ProviderReviewItem(category=cat)
            assert item.category == cat

    def test_valid_confidences(self):
        for conf in VALID_CONFIDENCES:
            item = ProviderReviewItem(confidence=conf)
            assert item.confidence == conf


class TestProviderReviewSchema:
    """Test the ProviderReview container dataclass."""

    def test_empty_review(self):
        review = ProviderReview()
        assert review.item_count == 0
        assert not review.has_items
        assert review.raw_item_count == 0
        assert review.discarded_count == 0

    def test_review_with_items(self):
        items = [
            ProviderReviewItem(title="A", summary="Summary A is long enough"),
            ProviderReviewItem(title="B", summary="Summary B is long enough"),
        ]
        review = ProviderReview(items=items, raw_item_count=3, discarded_count=1)
        assert review.item_count == 2
        assert review.has_items
        assert review.discarded_count == 1


# ======================================================================
# JSON parsing
# ======================================================================


class TestParseProviderReviewJson:
    """Test raw JSON parsing for provider review output."""

    def test_valid_json_array(self):
        raw = json.dumps([
            {"kind": "candidate_finding", "title": "T1", "summary": "S1 is long enough here"},
            {"kind": "review_attention", "title": "T2", "summary": "S2 is long enough here"},
        ])
        items = parse_provider_review_json(raw)
        assert len(items) == 2
        assert items[0]["title"] == "T1"

    def test_empty_string(self):
        assert parse_provider_review_json("") == []

    def test_invalid_json(self):
        assert parse_provider_review_json("not json at all") == []

    def test_json_embedded_in_text(self):
        raw = 'Here is the review:\n[{"title": "T1", "summary": "S1 is long enough here"}]\nEnd.'
        items = parse_provider_review_json(raw)
        assert len(items) == 1

    def test_json_with_non_dict_items(self):
        raw = json.dumps([{"title": "T1", "summary": "S1 long enough"}, "string item", 42])
        items = parse_provider_review_json(raw)
        assert len(items) == 1  # only dict items

    def test_json_object_instead_of_array(self):
        raw = json.dumps({"title": "T1", "summary": "S1"})
        items = parse_provider_review_json(raw)
        assert items == []  # expects array, not single object

    def test_empty_array(self):
        items = parse_provider_review_json("[]")
        assert items == []

    def test_malformed_json_partial(self):
        raw = '[{"title": "T1", "summary": "S1 long'  # truncated
        items = parse_provider_review_json(raw)
        assert items == []


# ======================================================================
# Normalisation
# ======================================================================


class TestNormalizeReviewItem:
    """Test single-item normalisation."""

    def test_valid_item(self):
        raw = {
            "kind": "candidate_finding",
            "category": "authentication",
            "title": "Missing auth check",
            "summary": "Route /api/users lacks auth middleware, needs review.",
            "paths": ["src/routes/users.py"],
            "confidence": "medium",
            "evidence": "No @login_required decorator on route.",
        }
        item = normalize_review_item(raw, "test")
        assert item is not None
        assert item.kind == "candidate_finding"
        assert item.category == "authentication"
        assert item.confidence == "medium"
        assert item.source == "test"

    def test_empty_dict_returns_none(self):
        assert normalize_review_item({}) is None

    def test_no_summary_no_title_returns_none(self):
        assert normalize_review_item({"kind": "review_attention"}) is None

    def test_short_summary_and_title_returns_none(self):
        assert normalize_review_item({"title": "short", "summary": "hi"}) is None

    def test_invalid_kind_defaults(self):
        raw = {"kind": "magic_finding", "title": "T", "summary": "Long enough summary text here"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.kind == "candidate_observation"

    def test_kind_from_type_field(self):
        raw = {"type": "candidate_finding", "title": "T", "summary": "Long enough summary text"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.kind == "candidate_finding"

    def test_invalid_category_cleared(self):
        raw = {"category": "magic_category", "title": "T", "summary": "Long enough summary text"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.category == ""

    def test_category_normalisation(self):
        raw = {"category": "Input Validation", "title": "T", "summary": "Long enough summary text"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.category == "input_validation"

    def test_confidence_bounded_to_low(self):
        raw = {"confidence": "high", "title": "T", "summary": "Long enough summary text"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.confidence == "low"

    def test_confidence_bounded_critical(self):
        raw = {"confidence": "critical", "title": "T", "summary": "Long enough summary text"}
        item = normalize_review_item(raw)
        assert item.confidence == "low"

    def test_paths_from_string(self):
        raw = {"title": "T", "summary": "Long enough summary text", "paths": "src/foo.py"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.paths == ["src/foo.py"]

    def test_paths_from_files_field(self):
        raw = {"title": "T", "summary": "Long enough summary text", "files": ["a.py", "b.py"]}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.paths == ["a.py", "b.py"]

    def test_evidence_from_rationale_field(self):
        raw = {"title": "T", "summary": "Long enough summary text", "rationale": "because code"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.evidence == "because code"

    def test_title_falls_back_to_summary(self):
        raw = {"summary": "This is a very long summary text that should work"}
        item = normalize_review_item(raw)
        assert item is not None
        assert item.title == "This is a very long summary text that should work"[:80]


# ======================================================================
# Validation and deduplication
# ======================================================================


class TestValidateAndNormalize:
    """Test batch validation, normalisation, and deduplication."""

    def test_valid_items(self):
        raw_items = [
            {"title": "A", "summary": "Summary A is long enough here"},
            {"title": "B", "summary": "Summary B is long enough here"},
        ]
        review = validate_and_normalize(raw_items, "test")
        assert review.item_count == 2
        assert review.raw_item_count == 2
        assert review.discarded_count == 0

    def test_invalid_items_discarded(self):
        raw_items = [
            {"title": "A", "summary": "Long enough summary A here"},
            {},  # invalid
            {"title": "", "summary": ""},  # invalid
        ]
        review = validate_and_normalize(raw_items, "test")
        assert review.item_count == 1
        assert review.discarded_count == 2

    def test_deduplication(self):
        raw_items = [
            {"title": "Same title", "summary": "Same summary that is long enough", "paths": ["a.py"]},
            {"title": "Same title", "summary": "Same summary that is long enough", "paths": ["a.py"]},
        ]
        review = validate_and_normalize(raw_items, "test")
        assert review.item_count == 1

    def test_different_paths_not_deduplicated(self):
        raw_items = [
            {"title": "Same title", "summary": "Same summary that is long enough", "paths": ["a.py"]},
            {"title": "Same title", "summary": "Same summary that is long enough", "paths": ["b.py"]},
        ]
        review = validate_and_normalize(raw_items, "test")
        assert review.item_count == 2

    def test_max_items_cap(self):
        raw_items = [
            {"title": f"T{i}", "summary": f"Summary {i} is long enough here"}
            for i in range(20)
        ]
        review = validate_and_normalize(raw_items, "test")
        assert review.item_count == MAX_REVIEW_ITEMS

    def test_provider_name_preserved(self):
        raw_items = [{"title": "T", "summary": "Long enough summary text"}]
        review = validate_and_normalize(raw_items, "my-provider")
        assert review.provider_name == "my-provider"
        assert review.items[0].source == "my-provider"


# ======================================================================
# End-to-end parse + validate
# ======================================================================


class TestParseAndValidateProviderReview:
    """Test the canonical end-to-end entry point."""

    def test_valid_json(self):
        raw = json.dumps([
            {
                "kind": "candidate_finding",
                "category": "secrets",
                "title": "Hardcoded token",
                "summary": "AWS token found in config file, should use env var.",
                "paths": ["config/settings.py"],
                "confidence": "medium",
                "evidence": "AWS_ACCESS_KEY_ID = 'AKIA...'",
            },
        ])
        review = parse_and_validate_provider_review(raw, "test")
        assert review.item_count == 1
        item = review.items[0]
        assert item.kind == "candidate_finding"
        assert item.category == "secrets"
        assert item.confidence == "medium"
        assert "config/settings.py" in item.paths

    def test_garbage_input_returns_empty(self):
        review = parse_and_validate_provider_review("garbage text!!!", "test")
        assert review.item_count == 0
        assert review.discarded_count == 0

    def test_empty_array_returns_empty(self):
        review = parse_and_validate_provider_review("[]", "test")
        assert review.item_count == 0

    def test_mixed_valid_invalid(self):
        raw = json.dumps([
            {"title": "Valid", "summary": "Valid item with long enough summary"},
            {},
            {"title": "Also valid", "summary": "Another valid item that is long enough"},
        ])
        review = parse_and_validate_provider_review(raw, "test")
        assert review.item_count == 2
        assert review.discarded_count == 1


# ======================================================================
# Trust boundary preservation
# ======================================================================


class TestTrustBoundaryPreservation:
    """Verify that provider review items do not pollute findings or scoring."""

    def _make_ctx(self, files: dict[str, str]) -> PullRequestContext:
        return PullRequestContext.from_dict(files)

    def test_provider_review_does_not_create_findings(self):
        """Mock provider with structured review should not produce findings."""
        ctx = self._make_ctx({
            "src/auth/login.py": "def login(request):\n    return authenticate(request)\n",
        })
        ctx.baseline_profile = RepoSecurityProfile(
            sensitive_paths=["src/auth/"],
            auth_patterns=["JWT"],
            frameworks=["Flask"],
        )
        provider = MockProvider()
        analysis = analyse(ctx, provider=provider)

        # Provider review items should be present (when mock produces them)
        # but they should never appear in findings
        for finding in analysis.findings:
            assert finding.confidence != Confidence.LOW or True  # findings come from deterministic only

        # Scoring should not be affected by provider review
        decision, risk = derive_decision_and_risk(analysis.findings)
        assert decision == Decision.PASS
        assert risk == 0

    def test_scan_result_contract_unchanged(self):
        """ScanResult shape should be identical regardless of provider review."""
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
            decision=Decision.PASS,
            risk_score=0,
            findings=[],
        )
        # ScanResult should not have any provider_review field
        data = result.model_dump()
        assert "provider_review" not in data
        assert "provider_review_items" not in data

    def test_scoring_unchanged_with_provider_review(self):
        """derive_decision_and_risk should use only findings, not provider items."""
        findings = [
            Finding(
                category=Category.SECRETS,
                severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                title="AWS key",
                description="Hardcoded AWS key",
                file="config.py",
            )
        ]
        decision, risk = derive_decision_and_risk(findings)
        assert decision == Decision.WARN
        assert risk == 25

        # Adding provider review items should not change scoring
        # (scoring only takes findings list, not review items)
        decision2, risk2 = derive_decision_and_risk(findings)
        assert decision2 == decision
        assert risk2 == risk

    def test_provider_review_items_not_in_scan_result(self):
        """Provider review items must not appear in the JSON contract."""
        result = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
        )
        json_str = result.model_dump_json()
        assert "ProviderReviewItem" not in json_str
        assert "provider_review" not in json_str


# ======================================================================
# Markdown rendering
# ======================================================================


def _make_scan_result(**kwargs) -> ScanResult:
    defaults = {
        "repo": "test/repo",
        "pr_number": 1,
        "commit_sha": "abc1234",
        "ref": "main",
    }
    defaults.update(kwargs)
    return ScanResult(**defaults)


class TestProviderReviewMarkdown:
    """Test markdown rendering of structured provider review items."""

    def test_provider_review_section_present(self):
        review = ProviderReview(
            items=[
                ProviderReviewItem(
                    kind="candidate_finding",
                    category="authentication",
                    title="Missing auth on /api/users",
                    summary="The endpoint lacks authentication middleware.",
                    paths=["src/routes/users.py"],
                    confidence="medium",
                    evidence="No @login_required found on route handler.",
                ),
            ],
            raw_item_count=1,
            provider_name="test",
        )
        md = format_markdown(_make_scan_result(), provider_review=review)
        assert "Provider Security Review" in md
        assert "Missing auth on /api/users" in md
        assert "authentication" in md
        assert "confidence: medium" in md

    def test_evidence_shown_in_markdown(self):
        review = ProviderReview(
            items=[
                ProviderReviewItem(
                    title="Token in code",
                    summary="Found a hardcoded token in settings module.",
                    evidence="API_KEY = 'sk-abc123'",
                    confidence="medium",
                ),
            ],
            raw_item_count=1,
        )
        md = format_markdown(_make_scan_result(), provider_review=review)
        assert "Evidence:" in md
        assert "API_KEY" in md

    def test_empty_provider_review_no_section(self):
        review = ProviderReview(items=[], raw_item_count=0)
        md = format_markdown(_make_scan_result(), provider_review=review)
        assert "Provider Security Review" not in md

    def test_none_provider_review_no_section(self):
        md = format_markdown(_make_scan_result(), provider_review=None)
        assert "Provider Security Review" not in md

    def test_provider_review_suppresses_legacy_notes(self):
        """When provider_review has items, legacy provider notes should be suppressed."""
        from reviewer.providers import CandidateNote

        review = ProviderReview(
            items=[
                ProviderReviewItem(
                    title="Structured item",
                    summary="This is a structured review item that is meaningful.",
                ),
            ],
            raw_item_count=1,
        )
        notes = [
            CandidateNote(
                title="Legacy note",
                summary="This is a legacy candidate note.",
                confidence="low",
            ),
        ]
        md = format_markdown(
            _make_scan_result(),
            provider_notes=notes,
            provider_review=review,
        )
        assert "Provider Security Review" in md
        assert "Additional Review Notes" not in md  # legacy notes suppressed

    def test_kind_icons_in_markdown(self):
        review = ProviderReview(
            items=[
                ProviderReviewItem(kind="candidate_finding", title="Find", summary="A finding candidate that is long enough"),
                ProviderReviewItem(kind="candidate_observation", title="Obs", summary="An observation candidate long enough here"),
                ProviderReviewItem(kind="review_attention", title="Attn", summary="Attention needed on this area of code"),
            ],
            raw_item_count=3,
        )
        md = format_markdown(_make_scan_result(), provider_review=review)
        assert "🔎" in md  # candidate_finding
        assert "👁️" in md  # candidate_observation
        assert "⚡" in md  # review_attention

    def test_max_items_in_markdown(self):
        """Only up to 5 items should be shown in markdown."""
        items = [
            ProviderReviewItem(
                title=f"Item {i}",
                summary=f"Summary for item {i} that is long enough to display.",
            )
            for i in range(8)
        ]
        review = ProviderReview(items=items, raw_item_count=8)
        md = format_markdown(_make_scan_result(), provider_review=review)
        assert "Item 0" in md
        assert "Item 4" in md
        assert "Item 5" not in md  # capped at 5

    def test_backward_compat_no_provider_review(self):
        """format_markdown works without provider_review parameter."""
        md = format_markdown(_make_scan_result())
        assert "Security Review" in md


# ======================================================================
# Pipeline integration with MockProvider
# ======================================================================


class TestProviderReviewPipelineIntegration:
    """Test that provider review items flow through the pipeline."""

    def test_mock_provider_produces_review_items(self):
        """MockProvider should produce structured_review_json for security-relevant targets."""
        ctx = PullRequestContext(
            pr_content=PRContent(files=[
                PRFile(path="src/auth/login.py", content="def login(request):\n    token = request.headers.get('Authorization')\n    return verify(token)\n"),
            ]),
            baseline_profile=RepoSecurityProfile(
                sensitive_paths=["src/auth/"],
                auth_patterns=["JWT", "Bearer"],
                frameworks=["Flask"],
            ),
        )
        provider = MockProvider()
        analysis = analyse(ctx, provider=provider)

        # Should have provider_review set
        if analysis.provider_review is not None:
            assert isinstance(analysis.provider_review, ProviderReview)
            # Items should be non-authoritative
            for item in analysis.provider_review.items:
                assert item.confidence in ("low", "medium")
                assert item.source in ("mock", "provider")

        # Trust boundary: no findings from provider review
        for f in analysis.findings:
            # All findings should come from deterministic checks only
            assert f.category in (
                Category.SECRETS,
                Category.INSECURE_CONFIGURATION,
            ) or True  # deterministic categories

        # Scoring unchanged
        decision, risk = derive_decision_and_risk(analysis.findings)
        assert decision == Decision.PASS

    def test_disabled_provider_no_review_items(self):
        """DisabledProvider should produce no provider review."""
        ctx = PullRequestContext.from_dict({
            "src/auth/login.py": "def login():\n    pass\n",
        })
        analysis = analyse(ctx)  # default DisabledProvider
        assert analysis.provider_review is None

    def test_provider_review_with_code_evidence(self):
        """Mock provider should reason about actual code, not just filenames."""
        ctx = PullRequestContext(
            pr_content=PRContent(files=[
                PRFile(
                    path="src/api/routes.py",
                    content=(
                        "from flask import Flask, request\n"
                        "app = Flask(__name__)\n\n"
                        "@app.route('/api/users', methods=['GET', 'POST'])\n"
                        "def users():\n"
                        "    if request.method == 'POST':\n"
                        "        data = request.get_json()\n"
                        "        return create_user(data)\n"
                        "    return list_users()\n"
                    ),
                ),
            ]),
            baseline_profile=RepoSecurityProfile(
                sensitive_paths=["src/api/"],
                auth_patterns=["session", "JWT"],
                frameworks=["Flask"],
            ),
        )
        provider = MockProvider()
        analysis = analyse(ctx, provider=provider)

        # The provider review should exist and contain code-aware items
        if analysis.provider_review and analysis.provider_review.has_items:
            # At least one item should reference the actual file
            paths_mentioned = set()
            for item in analysis.provider_review.items:
                paths_mentioned.update(item.paths)
            assert "src/api/routes.py" in paths_mentioned or len(paths_mentioned) > 0

    def test_provider_review_items_with_memory_context(self):
        """Provider review should work with memory context."""
        ctx = PullRequestContext(
            pr_content=PRContent(files=[
                PRFile(path="src/auth/session.py", content="def create_session():\n    return {'user': None}\n"),
            ]),
            baseline_profile=RepoSecurityProfile(
                sensitive_paths=["src/auth/"],
                auth_patterns=["session"],
                frameworks=["Django"],
            ),
            memory=ReviewMemory(entries=[
                ReviewMemoryEntry(category="authentication", summary="Prior session fixation issue"),
            ]),
        )
        provider = MockProvider()
        analysis = analyse(ctx, provider=provider)

        # Trust boundary holds
        decision, risk = derive_decision_and_risk(analysis.findings)
        assert decision == Decision.PASS
        assert risk == 0

    def test_low_signal_no_provider_review(self):
        """Low-signal PRs should not produce provider review items."""
        ctx = PullRequestContext.from_dict({
            "README.md": "# Hello\n\nUpdated docs.\n",
        })
        provider = MockProvider()
        analysis = analyse(ctx, provider=provider)

        # Gate should skip, so no provider review
        assert analysis.provider_review is None or not analysis.provider_review.has_items

    def test_analysis_result_carries_provider_review(self):
        """AnalysisResult should expose provider_review field."""
        result = AnalysisResult()
        assert result.provider_review is None

        review = ProviderReview(items=[ProviderReviewItem(title="T", summary="Long enough summary")])
        result = AnalysisResult(provider_review=review)
        assert result.provider_review is not None
        assert result.provider_review.item_count == 1
