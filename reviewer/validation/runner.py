"""Validation runner for PR validation scenarios (ADR-032).

Executes a ``ValidationScenario`` through the reviewer pipeline and
evaluates the result against its ``ExpectedBehavior``.  Returns a
structured ``ValidationResult`` with explicit pass/fail assertions.

The runner:
- builds ``PullRequestContext`` from scenario inputs
- resolves a provider (``DisabledProvider`` or ``MockProvider``)
- runs the engine ``analyse()``
- derives decision and risk_score
- formats markdown
- evaluates all declared expectations
- checks trust-boundary invariants

It never requires live credentials and never changes ``ScanResult``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.models import PRContent, PullRequestContext
from reviewer.planner import build_review_plan
from reviewer.bundle import build_review_bundle
from reviewer.provider_gate import ProviderGateResult, evaluate_provider_gate
from reviewer.providers import DisabledProvider, MockProvider
from reviewer.validation.scenario import ExpectedBehavior, ValidationScenario
from schemas.findings import ScanResult


@dataclass(frozen=True)
class Assertion:
    """A single pass/fail assertion from scenario validation.

    Attributes:
        name: Human-readable name of the assertion.
        passed: Whether the assertion passed.
        detail: Explanation on failure, empty on pass.
    """

    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationResult:
    """Result of running a validation scenario.

    Attributes:
        scenario_id: Id of the scenario that was run.
        passed: Whether all assertions passed.
        assertions: Individual assertion results.
        analysis: The raw AnalysisResult from the engine.
        scan_result: The constructed ScanResult.
        markdown: The formatted markdown output.
    """

    scenario_id: str
    assertions: list[Assertion] = field(default_factory=list)
    analysis: AnalysisResult | None = None
    scan_result: ScanResult | None = None
    markdown: str = ""

    @property
    def passed(self) -> bool:
        """True when every assertion passed."""
        return all(a.passed for a in self.assertions)

    @property
    def failed_assertions(self) -> list[Assertion]:
        """Return only the assertions that failed."""
        return [a for a in self.assertions if not a.passed]


def _build_context(scenario: ValidationScenario) -> PullRequestContext:
    """Build a PullRequestContext from scenario inputs."""
    pr_content = PRContent.from_dict(scenario.changed_files)
    return PullRequestContext(
        pr_content=pr_content,
        baseline_profile=scenario.baseline_profile,
        memory=scenario.memory,
    )


def _resolve_provider(scenario: ValidationScenario):
    """Return the appropriate provider for the scenario's mode."""
    if scenario.provider_mode == "mock":
        return MockProvider()
    return DisabledProvider()


def _evaluate_expectations(
    expected: ExpectedBehavior,
    analysis: AnalysisResult,
    scan_result: ScanResult,
    markdown: str,
    gate_result: ProviderGateResult,
) -> list[Assertion]:
    """Evaluate all declared expectations and return assertions."""
    assertions: list[Assertion] = []

    # -- Provider gate --
    if expected.provider_gate_invoked is not None:
        actual = gate_result.should_invoke
        assertions.append(Assertion(
            name="provider_gate_invoked",
            passed=actual == expected.provider_gate_invoked,
            detail=(
                f"expected gate {'invoked' if expected.provider_gate_invoked else 'skipped'}, "
                f"got {'invoked' if actual else 'skipped'}"
                if actual != expected.provider_gate_invoked else ""
            ),
        ))

    # -- Findings count --
    findings_count = len(analysis.findings)

    if expected.min_findings is not None:
        assertions.append(Assertion(
            name="min_findings",
            passed=findings_count >= expected.min_findings,
            detail=(
                f"expected >= {expected.min_findings} findings, got {findings_count}"
                if findings_count < expected.min_findings else ""
            ),
        ))

    if expected.max_findings is not None:
        assertions.append(Assertion(
            name="max_findings",
            passed=findings_count <= expected.max_findings,
            detail=(
                f"expected <= {expected.max_findings} findings, got {findings_count}"
                if findings_count > expected.max_findings else ""
            ),
        ))

    # -- Finding categories present --
    actual_categories = {f.category.value for f in analysis.findings}
    for cat in expected.finding_categories_present:
        assertions.append(Assertion(
            name=f"category_present:{cat}",
            passed=cat in actual_categories,
            detail=(
                f"expected category '{cat}' in findings, "
                f"got {sorted(actual_categories)}"
                if cat not in actual_categories else ""
            ),
        ))

    # -- Finding categories absent --
    for cat in expected.finding_categories_absent:
        assertions.append(Assertion(
            name=f"category_absent:{cat}",
            passed=cat not in actual_categories,
            detail=(
                f"expected category '{cat}' absent, "
                f"but found in {sorted(actual_categories)}"
                if cat in actual_categories else ""
            ),
        ))

    # -- Concerns presence --
    if expected.has_concerns is not None:
        has = len(analysis.concerns) > 0
        assertions.append(Assertion(
            name="has_concerns",
            passed=has == expected.has_concerns,
            detail=(
                f"expected concerns={'present' if expected.has_concerns else 'absent'}, "
                f"got {len(analysis.concerns)} concern(s)"
                if has != expected.has_concerns else ""
            ),
        ))

    # -- Observations presence --
    if expected.has_observations is not None:
        has = len(analysis.observations) > 0
        assertions.append(Assertion(
            name="has_observations",
            passed=has == expected.has_observations,
            detail=(
                f"expected observations={'present' if expected.has_observations else 'absent'}, "
                f"got {len(analysis.observations)} observation(s)"
                if has != expected.has_observations else ""
            ),
        ))

    # -- Markdown contains --
    for substr in expected.markdown_contains:
        assertions.append(Assertion(
            name=f"markdown_contains:{substr[:40]}",
            passed=substr in markdown,
            detail=(
                f"expected markdown to contain '{substr}'"
                if substr not in markdown else ""
            ),
        ))

    # -- Markdown omits --
    for substr in expected.markdown_omits:
        assertions.append(Assertion(
            name=f"markdown_omits:{substr[:40]}",
            passed=substr not in markdown,
            detail=(
                f"expected markdown to omit '{substr}'"
                if substr in markdown else ""
            ),
        ))

    # -- Max concerns --
    if expected.max_concerns is not None:
        concern_count = len(analysis.concerns)
        assertions.append(Assertion(
            name="max_concerns",
            passed=concern_count <= expected.max_concerns,
            detail=(
                f"expected <= {expected.max_concerns} concerns, got {concern_count}"
                if concern_count > expected.max_concerns else ""
            ),
        ))

    # -- Max observations --
    if expected.max_observations is not None:
        obs_count = len(analysis.observations)
        assertions.append(Assertion(
            name="max_observations",
            passed=obs_count <= expected.max_observations,
            detail=(
                f"expected <= {expected.max_observations} observations, got {obs_count}"
                if obs_count > expected.max_observations else ""
            ),
        ))

    # -- Provider notes presence --
    if expected.has_provider_notes is not None:
        has_notes = len(analysis.provider_notes) > 0
        assertions.append(Assertion(
            name="has_provider_notes",
            passed=has_notes == expected.has_provider_notes,
            detail=(
                f"expected provider_notes={'present' if expected.has_provider_notes else 'absent'}, "
                f"got {len(analysis.provider_notes)} note(s)"
                if has_notes != expected.has_provider_notes else ""
            ),
        ))

    # -- Expected markdown sections --
    for section in expected.expected_sections:
        found = f"## {section}" in markdown or f"### {section}" in markdown
        assertions.append(Assertion(
            name=f"section_present:{section[:40]}",
            passed=found,
            detail=(
                f"expected section '{section}' in markdown"
                if not found else ""
            ),
        ))

    # -- Absent markdown sections --
    for section in expected.absent_sections:
        found = f"## {section}" in markdown or f"### {section}" in markdown
        assertions.append(Assertion(
            name=f"section_absent:{section[:40]}",
            passed=not found,
            detail=(
                f"expected section '{section}' absent from markdown"
                if found else ""
            ),
        ))

    # -- Trust-boundary violations --
    if expected.no_trust_boundary_violations:
        # Provider output must not have created findings
        # (MockProvider/DisabledProvider never produce findings — but
        # let's verify the contract holds.)
        provider_findings = [
            f for f in analysis.findings
            if getattr(f, "source", None) == "provider"
        ]
        assertions.append(Assertion(
            name="trust_boundary:no_provider_findings",
            passed=len(provider_findings) == 0,
            detail=(
                f"found {len(provider_findings)} provider-sourced findings "
                "— trust boundary violated"
                if provider_findings else ""
            ),
        ))

        # Decision and risk_score must be derivable from findings alone
        expected_decision, expected_risk = derive_decision_and_risk(
            analysis.findings
        )
        assertions.append(Assertion(
            name="trust_boundary:decision_deterministic",
            passed=(
                scan_result.decision == expected_decision
                and scan_result.risk_score == expected_risk
            ),
            detail=(
                f"decision/risk mismatch: expected {expected_decision.value}/{expected_risk}, "
                f"got {scan_result.decision.value}/{scan_result.risk_score}"
                if (
                    scan_result.decision != expected_decision
                    or scan_result.risk_score != expected_risk
                )
                else ""
            ),
        ))

    return assertions


def run_scenario(scenario: ValidationScenario) -> ValidationResult:
    """Execute a validation scenario and evaluate expectations.

    Runs the full reviewer pipeline in an isolated, credential-free
    context and validates the output against the scenario's expected
    behavior.

    Args:
        scenario: The validation scenario to execute.

    Returns:
        A ``ValidationResult`` with structured assertion results.
    """
    # Build context
    ctx = _build_context(scenario)
    provider = _resolve_provider(scenario)

    # Run engine analysis
    analysis = analyse(ctx, provider=provider)

    # Derive decision and risk
    decision, risk_score = derive_decision_and_risk(analysis.findings)

    # Build ScanResult
    scan_result = ScanResult(
        repo="validation/scenario",
        pr_number=1,
        commit_sha="0000000",
        ref="validation",
        decision=decision,
        risk_score=risk_score,
        findings=analysis.findings,
    )

    # Format markdown
    markdown = format_markdown(
        scan_result,
        concerns=analysis.concerns,
        observations=analysis.observations,
        provider_notes=analysis.provider_notes,
        provider_review=analysis.provider_review,
    )

    # Evaluate provider gate independently for gate assertions
    plan = build_review_plan(ctx)
    bundle = build_review_bundle(ctx, plan)
    gate_result = evaluate_provider_gate(plan, bundle)

    # Evaluate expectations
    assertions = _evaluate_expectations(
        expected=scenario.expected,
        analysis=analysis,
        scan_result=scan_result,
        markdown=markdown,
        gate_result=gate_result,
    )

    return ValidationResult(
        scenario_id=scenario.id,
        assertions=assertions,
        analysis=analysis,
        scan_result=scan_result,
        markdown=markdown,
    )
