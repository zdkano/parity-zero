"""Tests for the realistic evaluation corpus, comparison, and scorecard (ADR-039).

Covers:
- realistic fixture loading and corpus structure
- realistic scenario execution and determinism
- provider comparison over realistic corpus
- scorecard construction and formatting
- output quality assertions for realistic fixtures
- quietness and value-add expectations
- trust boundary invariants across realistic corpus
- ScanResult contract stability
- regression safety (existing synthetic harness unchanged)
"""

from __future__ import annotations

import pytest

from reviewer.validation import (
    Assertion,
    ExpectedBehavior,
    ValidationScenario,
    ValidationResult,
    ModeResult,
    ComparisonResult,
    ScenarioScore,
    EvaluationScorecard,
    SCENARIOS,
    REALISTIC_SCENARIOS,
    get_scenario,
    get_realistic_scenario,
    list_scenario_ids,
    list_realistic_ids,
    get_scenarios_by_tag,
    list_tags,
    run_scenario,
    run_comparison,
    format_comparison_summary,
    build_scorecard,
    format_scorecard,
)
from reviewer.validation.realistic import _load_fixture, _FIXTURE_DIR
from reviewer.engine import AnalysisResult, derive_decision_and_risk
from schemas.findings import Category, ScanResult


# ======================================================================
# Part A — Realistic fixture corpus
# ======================================================================


class TestRealisticFixtureLoading:
    """Verify fixture files exist and load correctly."""

    def test_fixture_dir_exists(self):
        assert _FIXTURE_DIR.exists(), f"fixture dir {_FIXTURE_DIR} not found"

    def test_load_fixture_returns_content(self):
        content = _load_fixture("missing_auth_on_route", "api_users.py")
        assert isinstance(content, str)
        assert len(content) > 0

    def test_load_fixture_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_fixture("missing_auth_on_route", "nonexistent.py")

    def test_all_fixture_dirs_exist(self):
        expected_dirs = [
            "missing_auth_on_route",
            "authz_business_logic",
            "unsafe_sql_input",
            "insecure_session_config",
            "github_token_in_env",
            "harmless_utility_refactor",
            "docs_and_changelog",
            "test_coverage_expansion",
            "provider_helpful_auth",
            "memory_recurring_vuln",
        ]
        for d in expected_dirs:
            assert (_FIXTURE_DIR / d).exists(), f"fixture dir {d} not found"

    def test_fixture_content_is_non_trivial(self):
        """Each fixture file should have meaningful content."""
        for s in REALISTIC_SCENARIOS:
            for path, content in s.changed_files.items():
                assert len(content) > 50, (
                    f"scenario {s.id}: fixture {path} has only {len(content)} chars"
                )


class TestRealisticCorpusStructure:
    """Verify the realistic corpus is well-formed and complete."""

    def test_corpus_has_10_scenarios(self):
        assert len(REALISTIC_SCENARIOS) == 10

    def test_all_ids_unique(self):
        ids = list_realistic_ids()
        assert len(ids) == len(set(ids))

    def test_all_ids_prefixed(self):
        for s in REALISTIC_SCENARIOS:
            assert s.id.startswith("realistic-"), (
                f"realistic scenario {s.id} should be prefixed with 'realistic-'"
            )

    def test_all_have_realistic_tag(self):
        for s in REALISTIC_SCENARIOS:
            assert "realistic" in s.tags, (
                f"scenario {s.id} missing 'realistic' tag"
            )

    def test_all_have_description(self):
        for s in REALISTIC_SCENARIOS:
            assert s.description, f"scenario {s.id} missing description"

    def test_all_have_changed_files(self):
        for s in REALISTIC_SCENARIOS:
            assert s.changed_files, f"scenario {s.id} missing changed_files"

    def test_all_have_expected_behavior(self):
        for s in REALISTIC_SCENARIOS:
            assert isinstance(s.expected, ExpectedBehavior)

    def test_provider_mode_is_valid(self):
        for s in REALISTIC_SCENARIOS:
            assert s.provider_mode in ("disabled", "mock"), (
                f"scenario {s.id} has invalid provider_mode: {s.provider_mode}"
            )

    def test_expected_ids_present(self):
        ids = set(list_realistic_ids())
        expected = {
            "realistic-missing-auth-route",
            "realistic-authz-business-logic",
            "realistic-unsafe-sql-input",
            "realistic-insecure-session-config",
            "realistic-github-token-exposure",
            "realistic-harmless-refactor",
            "realistic-docs-changelog",
            "realistic-test-expansion",
            "realistic-provider-helpful-auth",
            "realistic-memory-recurring-vuln",
        }
        assert expected == ids

    def test_get_realistic_scenario_returns_match(self):
        for s in REALISTIC_SCENARIOS:
            found = get_realistic_scenario(s.id)
            assert found is not None
            assert found.id == s.id

    def test_get_realistic_scenario_returns_none_for_unknown(self):
        assert get_realistic_scenario("nonexistent") is None

    def test_corpus_is_deterministic(self):
        ids_1 = list_realistic_ids()
        ids_2 = list_realistic_ids()
        assert ids_1 == ids_2


class TestRealisticCorpusCategories:
    """Verify the realistic corpus covers meaningful scenario categories."""

    def test_has_auth_scenarios(self):
        auth = [s for s in REALISTIC_SCENARIOS if "auth" in s.tags]
        assert len(auth) >= 3, "need at least 3 auth-related realistic scenarios"

    def test_has_low_signal_scenarios(self):
        low = [s for s in REALISTIC_SCENARIOS if "low-signal" in s.tags]
        assert len(low) >= 3, "need at least 3 low-signal realistic scenarios"

    def test_has_deterministic_scenarios(self):
        det = [s for s in REALISTIC_SCENARIOS if "deterministic" in s.tags]
        assert len(det) >= 2, "need at least 2 deterministic realistic scenarios"

    def test_has_provider_value_scenarios(self):
        pv = [s for s in REALISTIC_SCENARIOS if "provider-value" in s.tags]
        assert len(pv) >= 4, "need at least 4 provider-value realistic scenarios"

    def test_has_memory_scenarios(self):
        mem = [s for s in REALISTIC_SCENARIOS if "memory" in s.tags]
        assert len(mem) >= 2, "need at least 2 memory-influenced realistic scenarios"


# ======================================================================
# Part A — Realistic scenario execution
# ======================================================================


class TestRealisticScenarioExecution:
    """Verify all realistic scenarios run and pass validation."""

    @pytest.mark.parametrize(
        "scenario",
        REALISTIC_SCENARIOS,
        ids=[s.id for s in REALISTIC_SCENARIOS],
    )
    def test_scenario_passes_validation(self, scenario):
        result = run_scenario(scenario)
        for a in result.failed_assertions:
            pytest.fail(
                f"[{scenario.id}] assertion '{a.name}' failed: {a.detail}"
            )

    @pytest.mark.parametrize(
        "scenario",
        REALISTIC_SCENARIOS,
        ids=[s.id for s in REALISTIC_SCENARIOS],
    )
    def test_scenario_produces_scan_result(self, scenario):
        result = run_scenario(scenario)
        assert isinstance(result.scan_result, ScanResult)

    @pytest.mark.parametrize(
        "scenario",
        REALISTIC_SCENARIOS,
        ids=[s.id for s in REALISTIC_SCENARIOS],
    )
    def test_scenario_produces_markdown(self, scenario):
        result = run_scenario(scenario)
        assert isinstance(result.markdown, str)
        assert len(result.markdown) > 0


# ======================================================================
# Part B — Provider comparison over realistic corpus
# ======================================================================


class TestRealisticComparison:
    """Validate provider comparison works with realistic fixtures."""

    @pytest.mark.parametrize(
        "scenario",
        REALISTIC_SCENARIOS,
        ids=[s.id for s in REALISTIC_SCENARIOS],
    )
    def test_comparison_returns_result(self, scenario):
        comp = run_comparison(scenario)
        assert isinstance(comp, ComparisonResult)

    @pytest.mark.parametrize(
        "scenario",
        REALISTIC_SCENARIOS,
        ids=[s.id for s in REALISTIC_SCENARIOS],
    )
    def test_comparison_trust_boundaries_held(self, scenario):
        comp = run_comparison(scenario)
        assert comp.trust_boundaries_held, (
            f"trust boundaries violated for {scenario.id}"
        )

    @pytest.mark.parametrize(
        "scenario",
        REALISTIC_SCENARIOS,
        ids=[s.id for s in REALISTIC_SCENARIOS],
    )
    def test_comparison_findings_stable(self, scenario):
        comp = run_comparison(scenario)
        assert comp.findings_stable, (
            f"deterministic findings not stable for {scenario.id}"
        )

    @pytest.mark.parametrize(
        "scenario",
        REALISTIC_SCENARIOS,
        ids=[s.id for s in REALISTIC_SCENARIOS],
    )
    def test_comparison_decision_stable(self, scenario):
        comp = run_comparison(scenario)
        assert comp.decision_stable, (
            f"decision not stable for {scenario.id}"
        )

    def test_comparison_format_summary_works(self):
        s = get_realistic_scenario("realistic-missing-auth-route")
        comp = run_comparison(s)
        summary = format_comparison_summary(comp)
        assert "realistic-missing-auth-route" in summary
        assert "disabled" in summary
        assert "mock" in summary

    def test_comparison_provider_adds_notes_for_auth(self):
        s = get_realistic_scenario("realistic-missing-auth-route")
        comp = run_comparison(s)
        assert comp.provider_added_notes, (
            "mock mode should add provider notes for auth scenario"
        )

    def test_comparison_no_notes_for_low_signal(self):
        for s in REALISTIC_SCENARIOS:
            if "low-signal" not in s.tags:
                continue
            comp = run_comparison(s)
            for mode, mr in comp.results.items():
                assert mr.provider_notes_count == 0, (
                    f"low-signal {s.id} [{mode}] should have no provider notes"
                )


class TestRealisticComparisonValueAdd:
    """Validate provider adds value where expected and stays quiet otherwise."""

    def test_provider_value_scenarios_add_observations(self):
        """Scenarios tagged provider-value should show value in comparison."""
        for s in REALISTIC_SCENARIOS:
            if s.provider_value_expected is not True:
                continue
            comp = run_comparison(s)
            mock_mr = comp.results.get("mock")
            disabled_mr = comp.results.get("disabled")
            if mock_mr and disabled_mr:
                # Mock should add observations or notes beyond disabled
                added = (
                    mock_mr.observation_count > disabled_mr.observation_count
                    or mock_mr.provider_notes_count > 0
                )
                assert added, (
                    f"scenario {s.id} expected provider value but mock "
                    f"didn't add observations/notes beyond disabled"
                )

    def test_gate_skip_scenarios_skip_in_both_modes(self):
        """Gate-skip scenarios should skip provider even in mock mode."""
        for s in REALISTIC_SCENARIOS:
            if "gate-skip" not in s.tags:
                continue
            comp = run_comparison(s)
            for mode, mr in comp.results.items():
                assert mr.gate_decision in ("skipped", "disabled", "unavailable"), (
                    f"gate-skip {s.id} [{mode}] had gate={mr.gate_decision}"
                )


# ======================================================================
# Part C — Scorecard
# ======================================================================


class TestScorecardConstruction:
    """Validate scorecard building and structure."""

    def test_build_scorecard_returns_scorecard(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert isinstance(sc, EvaluationScorecard)

    def test_scorecard_has_correct_corpus_size(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert sc.corpus_size == len(REALISTIC_SCENARIOS)

    def test_scorecard_has_per_scenario_scores(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert len(sc.scores) == len(REALISTIC_SCENARIOS)
        for score in sc.scores:
            assert isinstance(score, ScenarioScore)

    def test_scorecard_all_passed(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert sc.all_passed, "all realistic scenarios should pass"

    def test_scorecard_rates_are_valid(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        for rate_name in [
            "findings_stability_rate",
            "decision_stability_rate",
            "trust_boundary_rate",
            "gate_accuracy_rate",
            "quietness_rate",
            "provider_value_rate",
        ]:
            rate = getattr(sc, rate_name)
            assert 0.0 <= rate <= 1.0, (
                f"{rate_name} = {rate} out of range [0, 1]"
            )

    def test_scorecard_noise_rate_valid(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert 0.0 <= sc.noise_rate <= 1.0

    def test_scorecard_trust_boundary_rate_is_100(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert sc.trust_boundary_rate == 1.0, (
            "trust boundaries should hold for all realistic scenarios"
        )

    def test_scorecard_findings_stability_rate_is_100(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert sc.findings_stability_rate == 1.0, (
            "deterministic findings should be stable across modes"
        )

    def test_scorecard_decision_stability_rate_is_100(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assert sc.decision_stability_rate == 1.0, (
            "decisions should be stable across modes"
        )

    def test_scorecard_without_comparisons(self):
        sc = build_scorecard(REALISTIC_SCENARIOS, run_comparisons=False)
        assert sc.corpus_size == len(REALISTIC_SCENARIOS)
        # Without comparisons, stability rates default to 1.0 (safe)
        assert sc.findings_stability_rate == 1.0
        assert sc.decision_stability_rate == 1.0


class TestScorecardFormatting:
    """Validate scorecard formatting produces useful output."""

    def test_format_scorecard_returns_string(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        output = format_scorecard(sc)
        assert isinstance(output, str)

    def test_format_scorecard_contains_header(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        output = format_scorecard(sc)
        assert "Evaluation Scorecard" in output

    def test_format_scorecard_contains_rates(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        output = format_scorecard(sc)
        assert "Findings stability" in output
        assert "Decision stability" in output
        assert "Trust boundaries" in output
        assert "Gate accuracy" in output
        assert "Quietness" in output
        assert "Provider value-add" in output

    def test_format_scorecard_contains_scenario_ids(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        output = format_scorecard(sc)
        for s in REALISTIC_SCENARIOS:
            assert s.id in output

    def test_format_scorecard_contains_disclaimer(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        output = format_scorecard(sc)
        assert "not a scientific benchmark" in output


class TestScorecardSignals:
    """Validate that scorecard captures correct per-scenario signals."""

    def test_low_signal_scenarios_marked_quiet(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        for score in sc.scores:
            if "low-signal" in score.tags:
                assert score.quiet_when_expected is True, (
                    f"low-signal scenario {score.scenario_id} not quiet"
                )

    def test_low_signal_scenarios_not_noisy(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        for score in sc.scores:
            if "low-signal" in score.tags:
                assert not score.noisy, (
                    f"low-signal scenario {score.scenario_id} is noisy"
                )

    def test_gate_correctness_assessed(self):
        sc = build_scorecard(REALISTIC_SCENARIOS)
        assessed = [s for s in sc.scores if s.gate_correct is not None]
        assert len(assessed) > 0, "at least some scenarios should have gate expectations"
        for s in assessed:
            assert s.gate_correct, (
                f"scenario {s.scenario_id} has incorrect gate behavior"
            )


# ======================================================================
# Part D — Output quality and realism checks
# ======================================================================


class TestRealisticOutputQuality:
    """Output quality assertions for realistic fixtures."""

    def test_markdown_has_security_review_header(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            assert "Security Review" in result.markdown, (
                f"scenario {s.id} missing Security Review header"
            )

    def test_no_empty_findings_in_markdown_when_findings_exist(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            if len(result.analysis.findings) > 0:
                assert "No security findings" not in result.markdown, (
                    f"scenario {s.id} has findings but markdown says no findings"
                )

    def test_provider_notes_section_absent_when_no_notes(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            if len(result.analysis.provider_notes) == 0:
                assert "Provider Notes" not in result.markdown, (
                    f"scenario {s.id} has no provider notes but shows section"
                )

    def test_no_duplicate_finding_titles(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            pairs = [(f.title, f.file) for f in result.analysis.findings]
            assert len(pairs) == len(set(pairs)), (
                f"scenario {s.id} has duplicate finding title+file pairs"
            )

    def test_observation_paths_tied_to_changed_files(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            changed = set(s.changed_files.keys())
            for obs in result.analysis.observations:
                assert obs.path in changed, (
                    f"scenario {s.id}: observation for '{obs.path}' "
                    f"not in changed files {changed}"
                )

    def test_markdown_not_excessively_long_for_no_findings(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            if len(result.analysis.findings) == 0 and len(result.analysis.concerns) == 0:
                assert len(result.markdown) < 2000, (
                    f"scenario {s.id} has no findings/concerns but markdown "
                    f"is {len(result.markdown)} chars"
                )


class TestRealisticQuietnessExpectations:
    """Codify quietness expectations for realistic low-signal cases."""

    def test_low_signal_produce_no_findings(self):
        for s in REALISTIC_SCENARIOS:
            if "low-signal" not in s.tags:
                continue
            result = run_scenario(s)
            assert len(result.analysis.findings) == 0, (
                f"low-signal {s.id} produced {len(result.analysis.findings)} findings"
            )

    def test_low_signal_produce_no_concerns(self):
        for s in REALISTIC_SCENARIOS:
            if "low-signal" not in s.tags:
                continue
            result = run_scenario(s)
            assert len(result.analysis.concerns) == 0, (
                f"low-signal {s.id} produced {len(result.analysis.concerns)} concerns"
            )

    def test_low_signal_produce_no_observations(self):
        for s in REALISTIC_SCENARIOS:
            if "low-signal" not in s.tags:
                continue
            result = run_scenario(s)
            assert len(result.analysis.observations) == 0, (
                f"low-signal {s.id} produced {len(result.analysis.observations)} observations"
            )

    def test_low_signal_produce_no_provider_notes(self):
        for s in REALISTIC_SCENARIOS:
            if "low-signal" not in s.tags:
                continue
            result = run_scenario(s)
            assert len(result.analysis.provider_notes) == 0, (
                f"low-signal {s.id} produced {len(result.analysis.provider_notes)} notes"
            )

    def test_gate_skip_scenarios_gate_skipped(self):
        for s in REALISTIC_SCENARIOS:
            if "gate-skip" not in s.tags:
                continue
            result = run_scenario(s)
            gate = result.analysis.trace.provider_gate_decision
            assert gate in ("skipped", "disabled", "unavailable"), (
                f"gate-skip {s.id} had gate decision: {gate}"
            )


class TestRealisticValueAddExpectations:
    """Codify value-add expectations for provider-helpful scenarios."""

    def test_auth_scenarios_produce_concerns(self):
        for s in REALISTIC_SCENARIOS:
            if "auth" not in s.tags:
                continue
            result = run_scenario(s)
            assert len(result.analysis.concerns) > 0, (
                f"auth scenario {s.id} should produce concerns"
            )

    def test_auth_scenarios_produce_observations(self):
        for s in REALISTIC_SCENARIOS:
            if "auth" not in s.tags:
                continue
            result = run_scenario(s)
            assert len(result.analysis.observations) > 0, (
                f"auth scenario {s.id} should produce observations"
            )

    def test_provider_value_scenarios_produce_notes_in_mock_mode(self):
        for s in REALISTIC_SCENARIOS:
            if s.provider_value_expected is not True:
                continue
            if s.provider_mode != "mock":
                continue
            result = run_scenario(s)
            assert len(result.analysis.provider_notes) > 0, (
                f"provider-value scenario {s.id} should produce notes"
            )

    def test_deterministic_scenarios_detect_findings(self):
        for s in REALISTIC_SCENARIOS:
            if "deterministic" not in s.tags:
                continue
            result = run_scenario(s)
            assert len(result.analysis.findings) > 0, (
                f"deterministic scenario {s.id} should detect findings"
            )


class TestRealisticProviderBoundary:
    """Provider notes must remain non-authoritative in realistic corpus."""

    def test_provider_notes_never_create_findings(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            for f in result.analysis.findings:
                assert getattr(f, "source", None) != "provider", (
                    f"scenario {s.id}: finding sourced from provider"
                )

    def test_provider_notes_bounded(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            assert len(result.analysis.provider_notes) <= 10, (
                f"scenario {s.id}: {len(result.analysis.provider_notes)} notes"
            )

    def test_no_provider_notes_when_gated_out(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            gate = result.analysis.trace.provider_gate_decision
            if gate == "skipped":
                assert len(result.analysis.provider_notes) == 0, (
                    f"scenario {s.id}: gate skipped but has "
                    f"{len(result.analysis.provider_notes)} provider notes"
                )


# ======================================================================
# Trust boundary invariants across realistic corpus
# ======================================================================


class TestRealisticTrustBoundaries:
    """Trust boundaries must hold across all realistic scenarios."""

    def test_no_provider_sourced_findings(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            for f in result.analysis.findings:
                assert getattr(f, "source", None) != "provider"

    def test_decision_always_deterministic(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            expected_decision, expected_risk = derive_decision_and_risk(
                result.analysis.findings
            )
            assert result.scan_result.decision == expected_decision
            assert result.scan_result.risk_score == expected_risk

    def test_provider_notes_not_in_scan_result_json(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump()
            assert "provider_notes" not in json_data
            assert "concerns" not in json_data
            assert "observations" not in json_data


# ======================================================================
# ScanResult contract stability
# ======================================================================


class TestRealisticScanResultContract:
    """ScanResult contract must remain unchanged with realistic corpus."""

    def test_scan_result_json_round_trip(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump(mode="json")
            restored = ScanResult(**json_data)
            assert restored.decision == result.scan_result.decision
            assert restored.risk_score == result.scan_result.risk_score
            assert len(restored.findings) == len(result.scan_result.findings)

    def test_scan_result_has_required_fields(self):
        for s in REALISTIC_SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump()
            required = {
                "scan_id", "repo", "pr_number", "commit_sha",
                "ref", "decision", "risk_score", "findings",
            }
            assert required.issubset(json_data.keys())


# ======================================================================
# Regression safety — existing synthetic harness unchanged
# ======================================================================


class TestSyntheticHarnessRegression:
    """Verify that the synthetic corpus and existing tests are unaffected."""

    def test_synthetic_corpus_size_unchanged(self):
        assert len(SCENARIOS) == 13

    def test_synthetic_ids_unchanged(self):
        ids = set(list_scenario_ids())
        expected = {
            "auth-sensitive", "sensitive-config", "trivial-docs",
            "memory-influenced", "deterministic-only", "provider-enriched",
            "low-noise-tests", "pem-key-in-config", "plain-refactor",
            "provider-gated-out", "mixed-auth-and-tests",
            "dependency-lockfile", "input-validation-risk",
        }
        assert ids == expected

    def test_synthetic_scenarios_still_pass(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            assert result.passed, (
                f"synthetic scenario {s.id} failed: "
                + "; ".join(a.detail for a in result.failed_assertions)
            )

    def test_get_scenario_still_works(self):
        s = get_scenario("auth-sensitive")
        assert s is not None
        assert s.id == "auth-sensitive"

    def test_list_tags_still_works(self):
        tags = list_tags()
        assert len(tags) > 0
        assert "auth" in tags

    def test_get_scenarios_by_tag_still_works(self):
        auth = get_scenarios_by_tag("auth")
        assert len(auth) > 0
