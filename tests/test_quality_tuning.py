"""Quality-tuning assertions for parity-zero reviewer output (ADR-040).

These tests encode practical quality expectations driven by the realistic
evaluation corpus.  They focus on:

- Provider note quality (non-generic, file-specific, bounded)
- Observation specificity (file-referenced titles, no generic filler)
- Redundancy suppression (no duplicated wording across output layers)
- Low-signal quietness (weak contexts produce minimal output)
- Markdown readability (correct sectioning, concise, no redundancy)
- Trust boundary integrity (provider output non-authoritative)

These tests complement the evaluation/comparison harness and the existing
quality rubric assertions.  They are intentionally explicit and maintainable.
"""

from __future__ import annotations

import pytest

from reviewer.formatter import format_markdown
from reviewer.models import ReviewConcern, ReviewObservation
from reviewer.providers import CandidateNote, MockProvider, ReasoningRequest
from reviewer.reasoning import _suppress_overlapping_notes, _is_metadata_restatement
from reviewer.validation.realistic import REALISTIC_SCENARIOS, get_realistic_scenario
from reviewer.validation.runner import run_scenario
from reviewer.validation.comparison import run_comparison


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_AUTH_SCENARIO_IDS = [
    "realistic-missing-auth-route",
    "realistic-authz-business-logic",
    "realistic-provider-helpful-auth",
    "realistic-memory-recurring-vuln",
]

_LOW_SIGNAL_SCENARIO_IDS = [
    "realistic-harmless-refactor",
    "realistic-docs-changelog",
    "realistic-test-expansion",
]

_PROVIDER_VALUE_SCENARIO_IDS = [
    s.id for s in REALISTIC_SCENARIOS
    if s.provider_value_expected
]


def _run_all_realistic() -> dict:
    """Run all realistic scenarios and cache results."""
    results = {}
    for s in REALISTIC_SCENARIOS:
        results[s.id] = run_scenario(s)
    return results


# Cache realistic results at module level for performance.
_REALISTIC_RESULTS = None


def _get_results():
    global _REALISTIC_RESULTS
    if _REALISTIC_RESULTS is None:
        _REALISTIC_RESULTS = _run_all_realistic()
    return _REALISTIC_RESULTS


# ==================================================================
# Part C1 — Realistic output quality assertions
# ==================================================================


class TestAuthScenarioSpecificity:
    """Auth/sensitive scenarios produce specific, file-referenced output."""

    @pytest.mark.parametrize("scenario_id", _AUTH_SCENARIO_IDS)
    def test_observations_reference_changed_files(self, scenario_id):
        """Every observation references a file in the PR's changed files."""
        results = _get_results()
        vr = results[scenario_id]
        changed_paths = set()
        if vr.analysis.bundle:
            changed_paths = {item.path for item in vr.analysis.bundle.items}
        for obs in vr.analysis.observations:
            assert obs.path in changed_paths, (
                f"Observation '{obs.title}' references {obs.path} "
                f"which is not in changed files: {changed_paths}"
            )

    @pytest.mark.parametrize("scenario_id", _AUTH_SCENARIO_IDS)
    def test_observation_titles_include_filename(self, scenario_id):
        """Observation titles include the actual file basename."""
        results = _get_results()
        vr = results[scenario_id]
        for obs in vr.analysis.observations:
            if obs.path:
                basename = obs.path.rsplit("/", 1)[-1]
                assert basename in obs.title, (
                    f"Observation title '{obs.title}' should include "
                    f"file basename '{basename}'"
                )

    @pytest.mark.parametrize("scenario_id", _AUTH_SCENARIO_IDS)
    def test_auth_scenarios_produce_concerns(self, scenario_id):
        """Auth scenarios produce at least one concern."""
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.analysis.concerns) >= 1

    @pytest.mark.parametrize("scenario_id", _AUTH_SCENARIO_IDS)
    def test_auth_scenarios_produce_observations(self, scenario_id):
        """Auth scenarios produce at least one observation."""
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.analysis.observations) >= 1


class TestLowSignalQuietness:
    """Low-signal scenarios remain appropriately quiet."""

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_zero_findings(self, scenario_id):
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.analysis.findings) == 0

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_zero_concerns(self, scenario_id):
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.analysis.concerns) == 0

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_zero_observations(self, scenario_id):
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.analysis.observations) == 0

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_zero_provider_notes(self, scenario_id):
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.analysis.provider_notes) == 0

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_markdown_is_short(self, scenario_id):
        """Low-signal markdown should be concise (< 500 chars)."""
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.markdown) < 500, (
            f"{scenario_id} markdown is {len(vr.markdown)} chars, expected < 500"
        )

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_no_security_sections(self, scenario_id):
        """Low-signal markdown should not have concern/observation sections."""
        results = _get_results()
        vr = results[scenario_id]
        assert "Review Concerns" not in vr.markdown
        assert "Review Observations" not in vr.markdown
        assert "Additional Review Notes" not in vr.markdown
        assert "Provider Notes" not in vr.markdown


# ==================================================================
# Part C2 — Provider note quality assertions
# ==================================================================


class TestProviderNoteQuality:
    """Provider notes are non-generic, file-specific, and bounded."""

    def test_mock_provider_generates_file_specific_notes(self):
        """MockProvider notes reference actual changed file paths."""
        request = ReasoningRequest(
            changed_files_summary=[
                {"path": "src/auth/login.py", "review_reason": "sensitive_auth",
                 "focus_areas": "authentication"},
            ],
            plan_focus_areas=["authentication"],
        )
        response = MockProvider().reason(request)
        for note in response.structured_notes:
            # At least one related path should be from the changed files.
            assert any(
                "src/auth/login.py" in p
                for p in note.related_paths
            ) or "src/auth/login.py" in note.summary, (
                f"Note '{note.title}' does not reference the changed file"
            )

    def test_mock_provider_notes_not_generic_metadata(self):
        """MockProvider notes should not be pure metadata restatements."""
        request = ReasoningRequest(
            changed_files_summary=[
                {"path": "src/api/routes.py", "review_reason": "changed_file",
                 "focus_areas": ""},
            ],
        )
        response = MockProvider().reason(request)
        for note in response.structured_notes:
            # Notes should not be flagged as metadata restatements.
            assert not _is_metadata_restatement(note), (
                f"Note '{note.title}' is a metadata restatement: {note.summary}"
            )

    def test_metadata_restatement_detection(self):
        """Known metadata restatement patterns are detected."""
        meta_notes = [
            CandidateNote(title="File analysis summary",
                          summary="Analysed 3 changed file(s)."),
            CandidateNote(title="Review focus",
                          summary="Review plan focuses on authentication."),
            CandidateNote(title="Baseline",
                          summary="Repository baseline context: flask."),
            CandidateNote(title="Memory",
                          summary="Review memory categories: authorization."),
        ]
        for note in meta_notes:
            assert _is_metadata_restatement(note), (
                f"Expected metadata restatement: '{note.title}': {note.summary}"
            )

    def test_non_metadata_notes_pass_filter(self):
        """Genuine security observations are not flagged as metadata."""
        good_notes = [
            CandidateNote(
                title="Missing auth on CRUD endpoints",
                summary="The user management routes lack authentication decorators.",
            ),
            CandidateNote(
                title="SQL injection risk",
                summary="User input is interpolated directly into SQL query strings.",
            ),
        ]
        for note in good_notes:
            assert not _is_metadata_restatement(note), (
                f"Note should not be flagged as metadata: '{note.title}'"
            )

    @pytest.mark.parametrize("scenario_id", _PROVIDER_VALUE_SCENARIO_IDS)
    def test_provider_notes_bounded(self, scenario_id):
        """Provider notes count stays within bounds."""
        results = _get_results()
        vr = results[scenario_id]
        assert len(vr.analysis.provider_notes) <= 5


# ==================================================================
# Part C3 — Redundancy suppression assertions
# ==================================================================


class TestRedundancySuppression:
    """Redundancy is suppressed across output layers."""

    def test_overlapping_notes_suppressed(self):
        """Notes that heavily overlap with concerns are suppressed."""
        notes = [
            CandidateNote(
                title="Authentication boundary concern",
                summary="The authentication boundary may be affected by this change",
            ),
        ]
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Authentication boundary concern",
                summary="The authentication boundary may be affected by this change",
            ),
        ]
        result = _suppress_overlapping_notes(notes, concerns=concerns)
        assert len(result) == 0

    def test_metadata_restatements_filtered(self):
        """Metadata restatement notes are filtered during suppression."""
        notes = [
            CandidateNote(title="File analysis",
                          summary="Analysed 5 changed file(s) for security issues."),
            CandidateNote(title="Real observation",
                          summary="The auth middleware skips token validation on error paths."),
        ]
        result = _suppress_overlapping_notes(notes)
        assert len(result) == 1
        assert result[0].title == "Real observation"

    def test_short_notes_filtered(self):
        """Notes with very short summaries are filtered."""
        notes = [
            CandidateNote(title="Short", summary="Too short."),
            CandidateNote(title="Adequate",
                          summary="This endpoint may allow unauthenticated access."),
        ]
        result = _suppress_overlapping_notes(notes)
        assert len(result) == 1
        assert result[0].title == "Adequate"

    @pytest.mark.parametrize("scenario_id", _AUTH_SCENARIO_IDS)
    def test_no_duplicate_observation_titles(self, scenario_id):
        """No two observations in the same scenario share identical titles."""
        results = _get_results()
        vr = results[scenario_id]
        titles = [o.title for o in vr.analysis.observations]
        assert len(titles) == len(set(titles)), (
            f"Duplicate observation titles found: {titles}"
        )

    @pytest.mark.parametrize("scenario_id", _AUTH_SCENARIO_IDS)
    def test_no_duplicate_finding_identifiers(self, scenario_id):
        """No two findings share the same (title, file) pair."""
        results = _get_results()
        vr = results[scenario_id]
        pairs = [(f.title, f.file) for f in vr.analysis.findings]
        assert len(pairs) == len(set(pairs)), (
            f"Duplicate finding pairs found: {pairs}"
        )


# ==================================================================
# Part C4 — Markdown quality assertions
# ==================================================================


class TestMarkdownQuality:
    """Markdown output is readable, concise, and correctly structured."""

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS])
    def test_markdown_has_security_review_header(self, scenario_id):
        """Every scenario markdown starts with the Security Review header."""
        results = _get_results()
        vr = results[scenario_id]
        assert "## 🔒 parity-zero Security Review" in vr.markdown

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS])
    def test_markdown_has_footer(self, scenario_id):
        """Every scenario markdown ends with the metadata footer."""
        results = _get_results()
        vr = results[scenario_id]
        assert "Scan:" in vr.markdown
        assert "Decision:" in vr.markdown

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_low_signal_no_concern_section(self, scenario_id):
        """Low-signal scenarios have no concern section."""
        results = _get_results()
        vr = results[scenario_id]
        assert "### 🔍 Review Concerns" not in vr.markdown

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS)
    def test_low_signal_no_observation_section(self, scenario_id):
        """Low-signal scenarios have no observation section."""
        results = _get_results()
        vr = results[scenario_id]
        assert "### 📋 Review Observations" not in vr.markdown

    def test_no_redundant_recommendations_section(self):
        """Recommendations section is no longer emitted (inline instead)."""
        for s in REALISTIC_SCENARIOS:
            vr = _get_results()[s.id]
            assert "### Recommendations" not in vr.markdown, (
                f"Scenario {s.id} still has a Recommendations section"
            )

    def test_concern_dedup_limits_same_path_concerns(self):
        """When many concerns target the same path, markdown caps them."""
        from schemas.findings import ScanResult, Decision, ScanMeta
        scan = ScanResult(
            scan_id="test123456789", repo="test/repo",
            pr_number=1, commit_sha="abc1234def", ref="main",
            decision=Decision.PASS, risk_score=0, findings=[],
        )
        # 4 concerns all targeting the same file.
        concerns = [
            ReviewConcern(
                category="auth", title=f"Concern {i}",
                summary=f"Summary {i}", confidence="low",
                related_paths=["src/auth/login.py"],
            )
            for i in range(4)
        ]
        md = format_markdown(scan, concerns=concerns)
        # Should show at most 2 per path group.
        concern_count = md.count("- **Concern")
        assert concern_count <= 2, (
            f"Expected ≤2 concerns in markdown, got {concern_count}"
        )


# ==================================================================
# Part C5 — Comparison quality indicators
# ==================================================================


class TestComparisonQuality:
    """Comparison mode captures quality signals correctly."""

    @pytest.mark.parametrize("scenario_id", _PROVIDER_VALUE_SCENARIO_IDS[:2])
    def test_comparison_detects_provider_notes(self, scenario_id):
        """Comparison correctly detects when mock mode adds provider notes."""
        scenario = get_realistic_scenario(scenario_id)
        comp = run_comparison(scenario)
        assert comp.provider_added_notes is True

    @pytest.mark.parametrize("scenario_id", _LOW_SIGNAL_SCENARIO_IDS[:1])
    def test_comparison_low_signal_stays_quiet(self, scenario_id):
        """Comparison shows low-signal scenarios remain quiet in both modes."""
        scenario = get_realistic_scenario(scenario_id)
        comp = run_comparison(scenario)
        for mode, mr in comp.results.items():
            assert mr.provider_notes_count == 0, (
                f"{scenario_id} [{mode}] should have 0 provider notes"
            )

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS[:3]])
    def test_comparison_trust_boundaries_hold(self, scenario_id):
        """Trust boundaries hold in all comparison modes."""
        scenario = get_realistic_scenario(scenario_id)
        comp = run_comparison(scenario)
        assert comp.trust_boundaries_held is True

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS[:3]])
    def test_comparison_findings_stable(self, scenario_id):
        """Deterministic findings are stable across provider modes."""
        scenario = get_realistic_scenario(scenario_id)
        comp = run_comparison(scenario)
        assert comp.findings_stable is True

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS[:3]])
    def test_comparison_decision_stable(self, scenario_id):
        """Decision/risk is stable across provider modes."""
        scenario = get_realistic_scenario(scenario_id)
        comp = run_comparison(scenario)
        assert comp.decision_stable is True


# ==================================================================
# Trust boundary regression
# ==================================================================


class TestTrustBoundaryRegression:
    """Trust boundaries hold across all realistic scenarios."""

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS])
    def test_no_provider_sourced_findings(self, scenario_id):
        """No finding has source='provider'."""
        results = _get_results()
        vr = results[scenario_id]
        for f in vr.analysis.findings:
            assert getattr(f, "source", None) != "provider"

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS])
    def test_scan_result_json_clean(self, scenario_id):
        """ScanResult JSON does not leak non-authoritative fields."""
        results = _get_results()
        vr = results[scenario_id]
        json_str = vr.scan_result.model_dump_json()
        assert "provider_notes" not in json_str
        assert "concerns" not in json_str
        assert "observations" not in json_str

    @pytest.mark.parametrize("scenario_id", [s.id for s in REALISTIC_SCENARIOS])
    def test_scoring_deterministic(self, scenario_id):
        """Decision and risk_score derive from findings only."""
        from reviewer.engine import derive_decision_and_risk
        results = _get_results()
        vr = results[scenario_id]
        expected_dec, expected_risk = derive_decision_and_risk(vr.analysis.findings)
        assert vr.scan_result.decision == expected_dec
        assert vr.scan_result.risk_score == expected_risk
