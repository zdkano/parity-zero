"""Tests for the evaluation and benchmarking layer (ADR-038).

Covers:
- expanded scenario metadata / tags / expectations
- expanded corpus loading and determinism
- comparison mode (disabled vs mock)
- output quality assertions
- low-noise and usefulness checks
- trust boundary invariants across expanded corpus
- ScanResult contract stability with expanded corpus
- regression safety for existing harness behavior
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
    SCENARIOS,
    get_scenario,
    list_scenario_ids,
    get_scenarios_by_tag,
    list_tags,
    run_scenario,
    run_comparison,
    format_comparison_summary,
)
from reviewer.models import (
    PRContent,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)
from reviewer.providers import DisabledProvider, MockProvider
from reviewer.engine import AnalysisResult, derive_decision_and_risk
from schemas.findings import Category, ScanResult


# ======================================================================
# A1: Scenario metadata / tags / expectations
# ======================================================================


class TestScenarioMetadata:
    """Verify scenario metadata fields are well-formed."""

    def test_all_scenarios_have_tags(self):
        for s in SCENARIOS:
            assert isinstance(s.tags, list), f"scenario {s.id} tags not a list"

    def test_all_scenarios_have_security_focus(self):
        for s in SCENARIOS:
            assert isinstance(s.security_focus, list), (
                f"scenario {s.id} security_focus not a list"
            )

    def test_all_scenarios_have_provider_value_flag(self):
        for s in SCENARIOS:
            assert s.provider_value_expected in (True, False, None), (
                f"scenario {s.id} has invalid provider_value_expected"
            )

    def test_tags_are_strings(self):
        for s in SCENARIOS:
            for tag in s.tags:
                assert isinstance(tag, str), f"scenario {s.id} has non-string tag: {tag}"

    def test_security_focus_are_strings(self):
        for s in SCENARIOS:
            for focus in s.security_focus:
                assert isinstance(focus, str), (
                    f"scenario {s.id} has non-string security_focus: {focus}"
                )

    def test_get_scenarios_by_tag_returns_matches(self):
        auth_scenarios = get_scenarios_by_tag("auth")
        assert len(auth_scenarios) > 0
        for s in auth_scenarios:
            assert "auth" in s.tags

    def test_get_scenarios_by_tag_empty_for_nonexistent(self):
        assert get_scenarios_by_tag("nonexistent-tag") == []

    def test_list_tags_returns_sorted_unique(self):
        tags = list_tags()
        assert len(tags) > 0
        assert tags == sorted(tags)
        assert len(tags) == len(set(tags))

    def test_low_signal_scenarios_have_no_security_focus(self):
        for s in get_scenarios_by_tag("low-signal"):
            assert s.security_focus == [], (
                f"low-signal scenario {s.id} has security_focus: {s.security_focus}"
            )

    def test_provider_value_scenarios_use_mock(self):
        for s in get_scenarios_by_tag("provider-value"):
            assert s.provider_mode == "mock", (
                f"provider-value scenario {s.id} should use mock mode"
            )
            assert s.provider_value_expected is True, (
                f"provider-value scenario {s.id} should expect provider value"
            )

    def test_no_provider_scenarios_expect_no_value(self):
        for s in get_scenarios_by_tag("no-provider"):
            assert s.provider_value_expected is False, (
                f"no-provider scenario {s.id} should not expect provider value"
            )

    def test_gate_skip_scenarios_expect_gate_skipped(self):
        for s in get_scenarios_by_tag("gate-skip"):
            assert s.expected.provider_gate_invoked is False, (
                f"gate-skip scenario {s.id} should expect gate skipped"
            )


# ======================================================================
# A2: Expanded corpus loading and determinism
# ======================================================================


class TestExpandedCorpus:
    """Verify the expanded corpus is complete and deterministic."""

    def test_corpus_has_13_scenarios(self):
        assert len(SCENARIOS) == 13

    def test_all_ids_unique(self):
        ids = list_scenario_ids()
        assert len(ids) == len(set(ids))

    def test_expected_original_ids_present(self):
        ids = set(list_scenario_ids())
        original = {
            "auth-sensitive", "sensitive-config", "trivial-docs",
            "memory-influenced", "deterministic-only", "provider-enriched",
            "low-noise-tests",
        }
        assert original.issubset(ids)

    def test_expected_new_ids_present(self):
        ids = set(list_scenario_ids())
        new_ids = {
            "pem-key-in-config", "plain-refactor", "provider-gated-out",
            "mixed-auth-and-tests", "dependency-lockfile",
            "input-validation-risk",
        }
        assert new_ids.issubset(ids)

    def test_corpus_is_deterministic(self):
        """Running list_scenario_ids twice should return the same order."""
        ids_1 = list_scenario_ids()
        ids_2 = list_scenario_ids()
        assert ids_1 == ids_2

    def test_all_scenarios_have_description(self):
        for s in SCENARIOS:
            assert s.description, f"scenario {s.id} missing description"

    def test_all_scenarios_have_changed_files(self):
        for s in SCENARIOS:
            assert s.changed_files, f"scenario {s.id} missing changed_files"

    def test_all_scenarios_have_expected_behavior(self):
        for s in SCENARIOS:
            assert isinstance(s.expected, ExpectedBehavior)


# ======================================================================
# New scenario-specific tests
# ======================================================================


class TestPemKeyInConfigScenario:
    """Validate the PEM key in config scenario."""

    def test_scenario_passes(self):
        s = get_scenario("pem-key-in-config")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_secrets_detected(self):
        s = get_scenario("pem-key-in-config")
        result = run_scenario(s)
        cats = {f.category.value for f in result.analysis.findings}
        assert "secrets" in cats

    def test_exactly_one_finding(self):
        s = get_scenario("pem-key-in-config")
        result = run_scenario(s)
        assert len(result.analysis.findings) == 1


class TestPlainRefactorScenario:
    """Validate the plain refactor scenario stays quiet."""

    def test_scenario_passes(self):
        s = get_scenario("plain-refactor")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_no_findings(self):
        s = get_scenario("plain-refactor")
        result = run_scenario(s)
        assert len(result.analysis.findings) == 0

    def test_no_concerns(self):
        s = get_scenario("plain-refactor")
        result = run_scenario(s)
        assert len(result.analysis.concerns) == 0

    def test_no_observations(self):
        s = get_scenario("plain-refactor")
        result = run_scenario(s)
        assert len(result.analysis.observations) == 0


class TestProviderGatedOutScenario:
    """Validate provider gate correctly skips on weak context."""

    def test_scenario_passes(self):
        s = get_scenario("provider-gated-out")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_no_provider_notes(self):
        s = get_scenario("provider-gated-out")
        result = run_scenario(s)
        assert len(result.analysis.provider_notes) == 0

    def test_gate_skipped(self):
        s = get_scenario("provider-gated-out")
        result = run_scenario(s)
        assert result.analysis.trace.provider_gate_decision in ("skipped", "disabled")


class TestMixedAuthAndTestsScenario:
    """Validate mixed auth + test scenario focuses on auth code."""

    def test_scenario_passes(self):
        s = get_scenario("mixed-auth-and-tests")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_has_concerns(self):
        s = get_scenario("mixed-auth-and-tests")
        result = run_scenario(s)
        assert len(result.analysis.concerns) > 0

    def test_has_observations(self):
        s = get_scenario("mixed-auth-and-tests")
        result = run_scenario(s)
        assert len(result.analysis.observations) > 0


class TestDependencyLockfileScenario:
    """Validate dependency lockfile scenario stays quiet."""

    def test_scenario_passes(self):
        s = get_scenario("dependency-lockfile")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_no_findings(self):
        s = get_scenario("dependency-lockfile")
        result = run_scenario(s)
        assert len(result.analysis.findings) == 0

    def test_no_concerns(self):
        s = get_scenario("dependency-lockfile")
        result = run_scenario(s)
        assert len(result.analysis.concerns) == 0


class TestInputValidationRiskScenario:
    """Validate input validation risk scenario invokes provider."""

    def test_scenario_passes(self):
        s = get_scenario("input-validation-risk")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_has_concerns(self):
        s = get_scenario("input-validation-risk")
        result = run_scenario(s)
        assert len(result.analysis.concerns) > 0

    def test_gate_invoked(self):
        s = get_scenario("input-validation-risk")
        result = run_scenario(s)
        assert result.analysis.trace.provider_gate_decision in ("invoked",)


# ======================================================================
# B4/B5: Comparison mode
# ======================================================================


class TestComparisonMode:
    """Validate provider comparison functionality."""

    def test_comparison_returns_result(self):
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        assert isinstance(comp, ComparisonResult)

    def test_comparison_has_both_modes(self):
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        assert "disabled" in comp.results
        assert "mock" in comp.results

    def test_comparison_mode_results_are_mode_result(self):
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        for mode, mr in comp.results.items():
            assert isinstance(mr, ModeResult)
            assert mr.mode == mode

    def test_comparison_findings_stable_for_deterministic(self):
        """Deterministic findings should be the same across modes."""
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        assert comp.findings_stable, (
            "deterministic findings should be stable across modes"
        )

    def test_comparison_decision_stable(self):
        """Decision and risk_score should be the same across modes."""
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        assert comp.decision_stable

    def test_comparison_trust_boundaries_held(self):
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        assert comp.trust_boundaries_held

    def test_comparison_gate_differs_for_mock(self):
        """Mock mode should have different gate decision than disabled."""
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        assert comp.gate_differed

    def test_comparison_provider_adds_notes_for_auth(self):
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        assert comp.provider_added_notes

    def test_comparison_no_notes_for_trivial(self):
        """Trivial docs should produce no provider notes in either mode."""
        s = get_scenario("trivial-docs")
        comp = run_comparison(s)
        for mode, mr in comp.results.items():
            assert mr.provider_notes_count == 0, (
                f"trivial-docs [{mode}] should have no provider notes"
            )

    def test_comparison_format_summary(self):
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        summary = format_comparison_summary(comp)
        assert "auth-sensitive" in summary
        assert "disabled" in summary
        assert "mock" in summary
        assert "trust_boundary" in summary

    def test_comparison_with_custom_modes(self):
        """Can specify only one mode."""
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s, modes=["disabled"])
        assert len(comp.results) == 1
        assert "disabled" in comp.results

    def test_comparison_validation_results_accessible(self):
        s = get_scenario("auth-sensitive")
        comp = run_comparison(s)
        for mode in ("disabled", "mock"):
            vr = comp.validation_results[mode]
            assert isinstance(vr, ValidationResult)
            assert vr.analysis is not None
            assert vr.scan_result is not None

    def test_comparison_low_signal_stable(self):
        """Low-signal scenarios should be stable across modes."""
        for s in get_scenarios_by_tag("low-signal"):
            comp = run_comparison(s)
            assert comp.findings_stable, (
                f"low-signal scenario {s.id} should have stable findings"
            )
            assert comp.decision_stable, (
                f"low-signal scenario {s.id} should have stable decision"
            )
            assert comp.trust_boundaries_held, (
                f"low-signal scenario {s.id} should preserve trust boundaries"
            )


# ======================================================================
# C6: Output quality checks
# ======================================================================


class TestOutputQuality:
    """Validate output quality across scenarios."""

    def test_no_empty_findings_in_markdown_when_findings_exist(self):
        """If findings exist, markdown should not say 'No security findings'."""
        for s in SCENARIOS:
            result = run_scenario(s)
            if len(result.analysis.findings) > 0:
                assert "No security findings" not in result.markdown, (
                    f"scenario {s.id} has findings but markdown says no findings"
                )

    def test_markdown_has_security_review_header(self):
        """All scenario outputs should have the main header."""
        for s in SCENARIOS:
            result = run_scenario(s)
            assert "Security Review" in result.markdown, (
                f"scenario {s.id} missing Security Review header"
            )

    def test_findings_concerns_observations_clearly_separated(self):
        """In scenarios with all three, each should have its own section."""
        s = get_scenario("auth-sensitive")
        result = run_scenario(s)
        md = result.markdown
        # Findings appear in main body
        assert "findings" in md.lower() or "secrets" in md.lower()
        # Concerns and observations should be in separate sections if present
        if len(result.analysis.concerns) > 0:
            assert "concern" in md.lower() or "Contextual" in md
        if len(result.analysis.observations) > 0:
            assert "observation" in md.lower() or "Observation" in md

    def test_provider_notes_section_absent_when_no_notes(self):
        """If no provider notes, the Provider Notes section should not appear."""
        for s in SCENARIOS:
            result = run_scenario(s)
            if len(result.analysis.provider_notes) == 0:
                assert "Provider Notes" not in result.markdown or "## Provider" not in result.markdown, (
                    f"scenario {s.id} has no provider notes but shows Provider section"
                )

    def test_markdown_not_excessively_long_for_no_findings(self):
        """No-findings scenarios should produce concise markdown."""
        for s in SCENARIOS:
            result = run_scenario(s)
            if len(result.analysis.findings) == 0 and len(result.analysis.concerns) == 0:
                assert len(result.markdown) < 2000, (
                    f"scenario {s.id} has no findings/concerns but markdown "
                    f"is {len(result.markdown)} chars"
                )

    def test_no_duplicate_finding_titles(self):
        """Each scenario should not produce duplicate finding titles."""
        for s in SCENARIOS:
            result = run_scenario(s)
            titles = [f.title for f in result.analysis.findings]
            # Titles can repeat only if they're for different files
            title_file_pairs = [(f.title, f.file) for f in result.analysis.findings]
            assert len(title_file_pairs) == len(set(title_file_pairs)), (
                f"scenario {s.id} has duplicate finding title+file pairs"
            )

    def test_observation_paths_relate_to_changed_files(self):
        """Observations should reference paths from the changed files."""
        for s in SCENARIOS:
            result = run_scenario(s)
            changed_paths = set(s.changed_files.keys())
            for obs in result.analysis.observations:
                assert obs.path in changed_paths, (
                    f"scenario {s.id}: observation for '{obs.path}' "
                    f"not in changed files {changed_paths}"
                )


class TestProviderNotesQuality:
    """Validate provider notes do not become findings or overclaim."""

    def test_provider_notes_never_create_findings(self):
        """Provider notes must not result in findings."""
        for s in SCENARIOS:
            result = run_scenario(s)
            for f in result.analysis.findings:
                assert getattr(f, "source", None) != "provider", (
                    f"scenario {s.id}: finding '{f.title}' sourced from provider"
                )

    def test_provider_notes_bounded(self):
        """Provider notes should not exceed reasonable count."""
        for s in SCENARIOS:
            result = run_scenario(s)
            assert len(result.analysis.provider_notes) <= 10, (
                f"scenario {s.id}: {len(result.analysis.provider_notes)} "
                "provider notes exceeds bound"
            )

    def test_no_provider_notes_when_gated_out(self):
        """If gate skipped, no provider notes should be present."""
        for s in SCENARIOS:
            result = run_scenario(s)
            gate = result.analysis.trace.provider_gate_decision
            if gate == "skipped":
                assert len(result.analysis.provider_notes) == 0, (
                    f"scenario {s.id}: gate skipped but has "
                    f"{len(result.analysis.provider_notes)} provider notes"
                )


# ======================================================================
# C7: Low-noise and usefulness checks
# ======================================================================


class TestLowNoiseUsefulnessChecks:
    """Validate low-noise expectations for quiet scenarios."""

    def test_low_signal_scenarios_produce_no_findings(self):
        for s in get_scenarios_by_tag("low-signal"):
            result = run_scenario(s)
            assert len(result.analysis.findings) == 0, (
                f"low-signal scenario {s.id} produced "
                f"{len(result.analysis.findings)} findings"
            )

    def test_low_signal_scenarios_produce_no_concerns(self):
        for s in get_scenarios_by_tag("low-signal"):
            result = run_scenario(s)
            assert len(result.analysis.concerns) == 0, (
                f"low-signal scenario {s.id} produced "
                f"{len(result.analysis.concerns)} concerns"
            )

    def test_low_signal_scenarios_produce_no_observations(self):
        for s in get_scenarios_by_tag("low-signal"):
            result = run_scenario(s)
            assert len(result.analysis.observations) == 0, (
                f"low-signal scenario {s.id} produced "
                f"{len(result.analysis.observations)} observations"
            )

    def test_low_signal_scenarios_produce_no_provider_notes(self):
        for s in get_scenarios_by_tag("low-signal"):
            result = run_scenario(s)
            assert len(result.analysis.provider_notes) == 0, (
                f"low-signal scenario {s.id} produced "
                f"{len(result.analysis.provider_notes)} provider notes"
            )

    def test_no_provider_invocation_on_weak_context(self):
        """Scenarios with no sensitive/auth paths should not invoke provider."""
        for s in get_scenarios_by_tag("gate-skip"):
            result = run_scenario(s)
            gate = result.analysis.trace.provider_gate_decision
            assert gate in ("skipped", "disabled", "unavailable"), (
                f"gate-skip scenario {s.id} had gate decision: {gate}"
            )

    def test_deterministic_scenarios_work_without_provider(self):
        """Deterministic scenarios should produce same findings without provider."""
        for s in get_scenarios_by_tag("deterministic"):
            result = run_scenario(s)
            assert len(result.analysis.findings) > 0, (
                f"deterministic scenario {s.id} should detect findings"
            )


# ======================================================================
# Trust boundary invariants across expanded corpus
# ======================================================================


class TestExpandedTrustBoundaries:
    """Trust boundaries must hold across all 13 scenarios."""

    def test_no_provider_sourced_findings(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            for f in result.analysis.findings:
                assert getattr(f, "source", None) != "provider", (
                    f"scenario {s.id}: finding '{f.title}' has source=provider"
                )

    def test_decision_always_deterministic(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            expected_decision, expected_risk = derive_decision_and_risk(
                result.analysis.findings
            )
            assert result.scan_result.decision == expected_decision, (
                f"scenario {s.id}: decision mismatch"
            )
            assert result.scan_result.risk_score == expected_risk, (
                f"scenario {s.id}: risk_score mismatch"
            )

    def test_provider_notes_not_in_scan_result_json(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump()
            assert "provider_notes" not in json_data
            assert "concerns" not in json_data
            assert "observations" not in json_data

    def test_scan_result_has_required_fields(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump()
            required = {
                "scan_id", "repo", "pr_number", "commit_sha",
                "ref", "decision", "risk_score", "findings",
            }
            assert required.issubset(json_data.keys()), (
                f"scenario {s.id}: missing ScanResult fields"
            )


# ======================================================================
# ScanResult contract stability
# ======================================================================


class TestExpandedScanResultContract:
    """ScanResult contract must remain unchanged with expanded corpus."""

    def test_scan_result_json_round_trip(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump(mode="json")
            restored = ScanResult(**json_data)
            assert restored.decision == result.scan_result.decision
            assert restored.risk_score == result.scan_result.risk_score
            assert len(restored.findings) == len(result.scan_result.findings)

    def test_finding_fields_complete(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            for f in result.analysis.findings:
                assert f.category is not None
                assert f.severity is not None
                assert f.confidence is not None
                assert f.title
                assert f.description
                assert f.file


# ======================================================================
# All expanded scenarios pass (integration)
# ======================================================================


class TestAllExpandedScenariosPass:
    """Integration test: all 13 scenarios should pass validation."""

    @pytest.mark.parametrize(
        "scenario",
        SCENARIOS,
        ids=[s.id for s in SCENARIOS],
    )
    def test_scenario_passes_validation(self, scenario):
        result = run_scenario(scenario)
        for a in result.failed_assertions:
            pytest.fail(
                f"[{scenario.id}] assertion '{a.name}' failed: {a.detail}"
            )


# ======================================================================
# Comparison across all scenarios
# ======================================================================


class TestComparisonAcrossCorpus:
    """Run comparison for representative scenarios."""

    @pytest.mark.parametrize(
        "scenario_id",
        ["auth-sensitive", "trivial-docs", "deterministic-only", "provider-gated-out"],
    )
    def test_comparison_trust_boundaries(self, scenario_id):
        s = get_scenario(scenario_id)
        comp = run_comparison(s)
        assert comp.trust_boundaries_held, (
            f"trust boundaries violated for {scenario_id}"
        )

    @pytest.mark.parametrize(
        "scenario_id",
        ["auth-sensitive", "deterministic-only", "pem-key-in-config"],
    )
    def test_comparison_findings_stable(self, scenario_id):
        s = get_scenario(scenario_id)
        comp = run_comparison(s)
        assert comp.findings_stable, (
            f"deterministic findings not stable for {scenario_id}"
        )

    @pytest.mark.parametrize(
        "scenario_id",
        ["auth-sensitive", "deterministic-only", "pem-key-in-config"],
    )
    def test_comparison_decision_stable(self, scenario_id):
        s = get_scenario(scenario_id)
        comp = run_comparison(s)
        assert comp.decision_stable, (
            f"decision not stable for {scenario_id}"
        )
