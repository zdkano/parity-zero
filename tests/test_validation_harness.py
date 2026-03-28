"""Tests for the PR validation harness (ADR-032).

Covers:
- scenario loading and building
- validation runner behavior
- all curated scenarios
- provider gate expectations
- trust-boundary invariants
- no ScanResult contract changes
- disabled/mock provider compatibility
"""

from __future__ import annotations

import pytest

from reviewer.validation import (
    ExpectedBehavior,
    ValidationScenario,
    ValidationResult,
    SCENARIOS,
    get_scenario,
    list_scenario_ids,
    run_scenario,
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
# Scenario loading / building
# ======================================================================


class TestScenarioFormat:
    """Verify the scenario format and corpus are well-formed."""

    def test_scenarios_not_empty(self):
        assert len(SCENARIOS) > 0

    def test_all_scenarios_have_unique_ids(self):
        ids = list_scenario_ids()
        assert len(ids) == len(set(ids)), f"duplicate scenario ids: {ids}"

    def test_all_scenarios_have_description(self):
        for s in SCENARIOS:
            assert s.description, f"scenario {s.id} has no description"

    def test_all_scenarios_have_changed_files(self):
        for s in SCENARIOS:
            assert s.changed_files, f"scenario {s.id} has no changed_files"

    def test_all_scenarios_have_expected_behavior(self):
        for s in SCENARIOS:
            assert isinstance(s.expected, ExpectedBehavior), (
                f"scenario {s.id} has invalid expected behavior"
            )

    def test_provider_mode_is_valid(self):
        for s in SCENARIOS:
            assert s.provider_mode in ("disabled", "mock"), (
                f"scenario {s.id} has invalid provider_mode: {s.provider_mode}"
            )

    def test_get_scenario_returns_match(self):
        for s in SCENARIOS:
            found = get_scenario(s.id)
            assert found is not None
            assert found.id == s.id

    def test_get_scenario_returns_none_for_unknown(self):
        assert get_scenario("nonexistent-scenario") is None

    def test_list_scenario_ids_returns_all(self):
        ids = list_scenario_ids()
        assert len(ids) == len(SCENARIOS)
        for s in SCENARIOS:
            assert s.id in ids

    def test_expected_corpus_ids_present(self):
        """Verify the curated corpus contains the expected scenario ids."""
        ids = set(list_scenario_ids())
        expected_ids = {
            "auth-sensitive",
            "sensitive-config",
            "trivial-docs",
            "memory-influenced",
            "deterministic-only",
            "provider-enriched",
            "low-noise-tests",
        }
        assert expected_ids.issubset(ids), (
            f"missing expected scenarios: {expected_ids - ids}"
        )


class TestScenarioBuilding:
    """Verify that scenarios can be built into pipeline inputs."""

    def test_changed_files_build_to_pr_content(self):
        for s in SCENARIOS:
            pr = PRContent.from_dict(s.changed_files)
            assert pr.file_count == len(s.changed_files)

    def test_scenario_with_baseline_builds_context(self):
        s = get_scenario("auth-sensitive")
        assert s is not None
        ctx = PullRequestContext(
            pr_content=PRContent.from_dict(s.changed_files),
            baseline_profile=s.baseline_profile,
            memory=s.memory,
        )
        assert ctx.has_baseline
        assert not ctx.has_memory

    def test_scenario_with_memory_builds_context(self):
        s = get_scenario("memory-influenced")
        assert s is not None
        ctx = PullRequestContext(
            pr_content=PRContent.from_dict(s.changed_files),
            baseline_profile=s.baseline_profile,
            memory=s.memory,
        )
        assert ctx.has_baseline
        assert ctx.has_memory

    def test_minimal_scenario_builds_context(self):
        s = get_scenario("trivial-docs")
        assert s is not None
        ctx = PullRequestContext(
            pr_content=PRContent.from_dict(s.changed_files),
            baseline_profile=s.baseline_profile,
            memory=s.memory,
        )
        assert not ctx.has_baseline
        assert not ctx.has_memory


# ======================================================================
# Validation runner behavior
# ======================================================================


class TestValidationRunner:
    """Verify that the validation runner produces structured results."""

    def test_run_returns_validation_result(self):
        s = SCENARIOS[0]
        result = run_scenario(s)
        assert isinstance(result, ValidationResult)

    def test_result_has_scenario_id(self):
        s = SCENARIOS[0]
        result = run_scenario(s)
        assert result.scenario_id == s.id

    def test_result_has_assertions(self):
        s = SCENARIOS[0]
        result = run_scenario(s)
        assert len(result.assertions) > 0

    def test_result_has_analysis(self):
        s = SCENARIOS[0]
        result = run_scenario(s)
        assert isinstance(result.analysis, AnalysisResult)

    def test_result_has_scan_result(self):
        s = SCENARIOS[0]
        result = run_scenario(s)
        assert isinstance(result.scan_result, ScanResult)

    def test_result_has_markdown(self):
        s = SCENARIOS[0]
        result = run_scenario(s)
        assert isinstance(result.markdown, str)
        assert len(result.markdown) > 0

    def test_passed_property(self):
        """A result with all-passing assertions should report passed."""
        s = get_scenario("trivial-docs")
        assert s is not None
        result = run_scenario(s)
        if result.passed:
            assert len(result.failed_assertions) == 0
        else:
            assert len(result.failed_assertions) > 0

    def test_failed_assertions_accessible(self):
        s = SCENARIOS[0]
        result = run_scenario(s)
        for a in result.failed_assertions:
            assert not a.passed
            assert a.detail  # failed assertions should have explanation


class TestRunnerWithCustomScenario:
    """Verify runner works with ad-hoc scenarios beyond corpus."""

    def test_custom_empty_file_scenario(self):
        s = ValidationScenario(
            id="custom-empty",
            description="Custom scenario with harmless content",
            changed_files={"src/utils.py": "def add(a, b): return a + b\n"},
            expected=ExpectedBehavior(
                max_findings=0,
                no_trust_boundary_violations=True,
            ),
        )
        result = run_scenario(s)
        assert isinstance(result, ValidationResult)
        assert result.scenario_id == "custom-empty"

    def test_custom_scenario_with_mock_provider(self):
        s = ValidationScenario(
            id="custom-mock",
            description="Custom scenario with mock provider",
            changed_files={"src/app.py": "import os\nprint('hello')\n"},
            provider_mode="mock",
            expected=ExpectedBehavior(
                no_trust_boundary_violations=True,
            ),
        )
        result = run_scenario(s)
        assert isinstance(result, ValidationResult)


# ======================================================================
# Representative scenario validation
# ======================================================================


class TestAuthSensitiveScenario:
    """Validate the auth-sensitive scenario behaves as expected."""

    def test_scenario_passes(self):
        s = get_scenario("auth-sensitive")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_produces_findings(self):
        s = get_scenario("auth-sensitive")
        assert s is not None
        result = run_scenario(s)
        assert len(result.analysis.findings) >= 1

    def test_secrets_category_detected(self):
        s = get_scenario("auth-sensitive")
        assert s is not None
        result = run_scenario(s)
        cats = {f.category.value for f in result.analysis.findings}
        assert "secrets" in cats

    def test_provider_gate_invoked(self):
        s = get_scenario("auth-sensitive")
        assert s is not None
        result = run_scenario(s)
        gate_assertions = [
            a for a in result.assertions if a.name == "provider_gate_invoked"
        ]
        assert len(gate_assertions) == 1
        assert gate_assertions[0].passed


class TestSensitiveConfigScenario:
    """Validate the sensitive-config scenario."""

    def test_scenario_passes(self):
        s = get_scenario("sensitive-config")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_insecure_config_detected(self):
        s = get_scenario("sensitive-config")
        assert s is not None
        result = run_scenario(s)
        cats = {f.category.value for f in result.analysis.findings}
        assert "insecure_configuration" in cats

    def test_multiple_findings(self):
        s = get_scenario("sensitive-config")
        assert s is not None
        result = run_scenario(s)
        assert len(result.analysis.findings) >= 2


class TestTrivialDocsScenario:
    """Validate the trivial-docs scenario produces no findings."""

    def test_scenario_passes(self):
        s = get_scenario("trivial-docs")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_no_findings(self):
        s = get_scenario("trivial-docs")
        assert s is not None
        result = run_scenario(s)
        assert len(result.analysis.findings) == 0

    def test_provider_gate_skipped(self):
        s = get_scenario("trivial-docs")
        assert s is not None
        result = run_scenario(s)
        gate_assertions = [
            a for a in result.assertions if a.name == "provider_gate_invoked"
        ]
        assert len(gate_assertions) == 1
        assert gate_assertions[0].passed

    def test_clean_markdown(self):
        s = get_scenario("trivial-docs")
        assert s is not None
        result = run_scenario(s)
        assert "No security findings" in result.markdown


class TestMemoryInfluencedScenario:
    """Validate the memory-influenced scenario."""

    def test_scenario_passes(self):
        s = get_scenario("memory-influenced")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_concerns_present(self):
        s = get_scenario("memory-influenced")
        assert s is not None
        result = run_scenario(s)
        assert len(result.analysis.concerns) > 0

    def test_provider_gate_invoked(self):
        s = get_scenario("memory-influenced")
        assert s is not None
        result = run_scenario(s)
        gate_assertions = [
            a for a in result.assertions if a.name == "provider_gate_invoked"
        ]
        assert len(gate_assertions) == 1
        assert gate_assertions[0].passed


class TestDeterministicOnlyScenario:
    """Validate the deterministic-only scenario."""

    def test_scenario_passes(self):
        s = get_scenario("deterministic-only")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_secrets_detected(self):
        s = get_scenario("deterministic-only")
        assert s is not None
        result = run_scenario(s)
        cats = {f.category.value for f in result.analysis.findings}
        assert "secrets" in cats

    def test_findings_are_deterministic(self):
        """Running same scenario twice should produce same findings."""
        s = get_scenario("deterministic-only")
        assert s is not None
        r1 = run_scenario(s)
        r2 = run_scenario(s)
        assert len(r1.analysis.findings) == len(r2.analysis.findings)
        cats1 = {f.category.value for f in r1.analysis.findings}
        cats2 = {f.category.value for f in r2.analysis.findings}
        assert cats1 == cats2


class TestProviderEnrichedScenario:
    """Validate the provider-enriched scenario."""

    def test_scenario_passes(self):
        s = get_scenario("provider-enriched")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_observations_present(self):
        s = get_scenario("provider-enriched")
        assert s is not None
        result = run_scenario(s)
        assert len(result.analysis.observations) > 0

    def test_provider_gate_invoked(self):
        s = get_scenario("provider-enriched")
        assert s is not None
        result = run_scenario(s)
        gate_assertions = [
            a for a in result.assertions if a.name == "provider_gate_invoked"
        ]
        assert len(gate_assertions) == 1
        assert gate_assertions[0].passed


class TestLowNoiseTestScenario:
    """Validate the low-noise test-only scenario."""

    def test_scenario_passes(self):
        s = get_scenario("low-noise-tests")
        assert s is not None
        result = run_scenario(s)
        for a in result.failed_assertions:
            pytest.fail(f"assertion '{a.name}' failed: {a.detail}")

    def test_no_findings(self):
        s = get_scenario("low-noise-tests")
        assert s is not None
        result = run_scenario(s)
        assert len(result.analysis.findings) == 0

    def test_no_concerns(self):
        s = get_scenario("low-noise-tests")
        assert s is not None
        result = run_scenario(s)
        assert len(result.analysis.concerns) == 0


# ======================================================================
# Provider gate expectations
# ======================================================================


class TestProviderGateExpectations:
    """Validate provider gate behavior across scenarios."""

    def test_auth_sensitive_triggers_gate(self):
        s = get_scenario("auth-sensitive")
        assert s is not None
        result = run_scenario(s)
        assert result.analysis.trace.provider_gate_decision in (
            "invoked", "disabled", "unavailable"
        )

    def test_trivial_docs_skips_gate(self):
        s = get_scenario("trivial-docs")
        assert s is not None
        result = run_scenario(s)
        # Provider is disabled so gate may show as 'disabled' or 'skipped'
        assert result.analysis.trace.provider_gate_decision in (
            "skipped", "disabled", "unavailable"
        )

    def test_all_scenarios_have_gate_decision(self):
        valid_decisions = {"invoked", "skipped", "disabled", "unavailable"}
        for s in SCENARIOS:
            result = run_scenario(s)
            assert result.analysis.trace.provider_gate_decision in valid_decisions, (
                f"scenario {s.id} has unexpected gate decision: "
                f"'{result.analysis.trace.provider_gate_decision}'"
            )


# ======================================================================
# Trust-boundary invariants
# ======================================================================


class TestTrustBoundaryInvariants:
    """Validate that trust boundaries hold across all scenarios."""

    def test_no_provider_sourced_findings(self):
        """No scenario should produce findings attributed to a provider."""
        for s in SCENARIOS:
            result = run_scenario(s)
            for f in result.analysis.findings:
                assert getattr(f, "source", None) != "provider", (
                    f"scenario {s.id}: finding '{f.title}' has source=provider"
                )

    def test_decision_always_deterministic(self):
        """Decision and risk_score must derive from findings alone."""
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
        """Provider notes must not appear in ScanResult JSON."""
        for s in SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump()
            assert "provider_notes" not in json_data, (
                f"scenario {s.id}: provider_notes leaked into ScanResult"
            )
            assert "concerns" not in json_data, (
                f"scenario {s.id}: concerns leaked into ScanResult"
            )
            assert "observations" not in json_data, (
                f"scenario {s.id}: observations leaked into ScanResult"
            )


# ======================================================================
# ScanResult contract stability
# ======================================================================


class TestScanResultContractUnchanged:
    """Verify the validation harness does not alter ScanResult."""

    def test_scan_result_json_round_trip(self):
        """ScanResult should serialize and deserialize cleanly."""
        s = get_scenario("deterministic-only")
        assert s is not None
        result = run_scenario(s)
        json_data = result.scan_result.model_dump(mode="json")
        restored = ScanResult(**json_data)
        assert restored.decision == result.scan_result.decision
        assert restored.risk_score == result.scan_result.risk_score
        assert len(restored.findings) == len(result.scan_result.findings)

    def test_scan_result_has_required_fields(self):
        for s in SCENARIOS:
            result = run_scenario(s)
            json_data = result.scan_result.model_dump()
            required = {"scan_id", "repo", "pr_number", "commit_sha", "ref",
                        "decision", "risk_score", "findings"}
            assert required.issubset(json_data.keys()), (
                f"scenario {s.id}: missing ScanResult fields"
            )

    def test_finding_fields_complete(self):
        """All findings should have the required schema fields."""
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
# Disabled/mock provider compatibility
# ======================================================================


class TestProviderCompatibility:
    """Validate harness works with both disabled and mock providers."""

    def test_disabled_provider_scenarios_pass(self):
        disabled_scenarios = [
            s for s in SCENARIOS if s.provider_mode == "disabled"
        ]
        assert len(disabled_scenarios) > 0
        for s in disabled_scenarios:
            result = run_scenario(s)
            assert isinstance(result, ValidationResult), (
                f"scenario {s.id} did not produce a ValidationResult"
            )

    def test_mock_provider_scenarios_pass(self):
        mock_scenarios = [
            s for s in SCENARIOS if s.provider_mode == "mock"
        ]
        assert len(mock_scenarios) > 0
        for s in mock_scenarios:
            result = run_scenario(s)
            assert isinstance(result, ValidationResult), (
                f"scenario {s.id} did not produce a ValidationResult"
            )

    def test_same_scenario_works_with_both_modes(self):
        """Running a scenario with disabled vs mock should both work."""
        base = get_scenario("auth-sensitive")
        assert base is not None

        # Run with mock (as defined)
        result_mock = run_scenario(base)
        assert isinstance(result_mock, ValidationResult)

        # Create identical scenario but with disabled provider
        disabled_variant = ValidationScenario(
            id="auth-sensitive-disabled",
            description=base.description,
            changed_files=base.changed_files,
            baseline_profile=base.baseline_profile,
            memory=base.memory,
            provider_mode="disabled",
            expected=ExpectedBehavior(
                min_findings=1,
                finding_categories_present=["secrets"],
                no_trust_boundary_violations=True,
            ),
        )
        result_disabled = run_scenario(disabled_variant)
        assert isinstance(result_disabled, ValidationResult)

        # Both should detect the same deterministic findings
        cats_mock = {f.category.value for f in result_mock.analysis.findings}
        cats_disabled = {
            f.category.value for f in result_disabled.analysis.findings
        }
        assert "secrets" in cats_mock
        assert "secrets" in cats_disabled


# ======================================================================
# All scenarios pass (integration)
# ======================================================================


class TestAllScenariosPass:
    """Integration test: all curated scenarios should pass validation."""

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
