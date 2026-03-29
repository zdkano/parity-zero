"""Lightweight evaluation scorecard for reviewer tuning (ADR-039).

Produces a structured summary of how the reviewer behaves across a set
of scenarios.  Designed for practical tuning — not a scientific
benchmark.

The scorecard captures:
- findings stability across provider modes
- decision stability
- provider value-add (observations/notes)
- gate correctness (invoke/skip where expected)
- trust-boundary integrity
- quietness on low-signal scenarios
- noise indicators

Usage::

    from reviewer.validation.scorecard import build_scorecard, format_scorecard
    from reviewer.validation.realistic import REALISTIC_SCENARIOS

    scorecard = build_scorecard(REALISTIC_SCENARIOS)
    print(format_scorecard(scorecard))
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reviewer.validation.comparison import ComparisonResult, run_comparison
from reviewer.validation.runner import ValidationResult, run_scenario
from reviewer.validation.scenario import ValidationScenario


# ------------------------------------------------------------------
# Scorecard data structure
# ------------------------------------------------------------------


@dataclass
class ScenarioScore:
    """Per-scenario evaluation signals.

    Attributes:
        scenario_id: Scenario identifier.
        tags: Scenario tags.
        passed: Whether all scenario assertions passed.
        findings_count: Number of findings produced.
        concern_count: Number of concerns produced.
        observation_count: Number of observations produced.
        provider_notes_count: Number of provider notes produced.
        gate_decision: Provider gate decision string.
        decision: Reviewer decision (pass/warn/block).
        risk_score: Computed risk score.
        findings_stable: Whether findings match across modes (from comparison).
        decision_stable: Whether decision matches across modes.
        provider_added_value: Whether provider mode added observations/notes.
        gate_correct: Whether gate behavior matches expectation.
        trust_boundary_ok: Whether trust boundaries held.
        quiet_when_expected: Whether the scenario stayed quiet when it should.
        noisy: Whether the scenario produced unexpected output.
    """

    scenario_id: str
    tags: list[str] = field(default_factory=list)
    passed: bool = True
    findings_count: int = 0
    concern_count: int = 0
    observation_count: int = 0
    provider_notes_count: int = 0
    gate_decision: str = ""
    decision: str = ""
    risk_score: int = 0
    findings_stable: bool | None = None
    decision_stable: bool | None = None
    provider_added_value: bool | None = None
    gate_correct: bool | None = None
    trust_boundary_ok: bool = True
    quiet_when_expected: bool | None = None
    noisy: bool = False


@dataclass
class EvaluationScorecard:
    """Aggregate evaluation scorecard across a corpus.

    Attributes:
        corpus_size: Number of scenarios evaluated.
        scores: Per-scenario scores.
        all_passed: Whether every scenario assertion passed.
        findings_stability_rate: Fraction of compared scenarios with stable findings.
        decision_stability_rate: Fraction of compared scenarios with stable decisions.
        trust_boundary_rate: Fraction of scenarios where trust boundaries held.
        gate_accuracy_rate: Fraction of scenarios where gate behavior was correct.
        quietness_rate: Fraction of low-signal scenarios that stayed quiet.
        noise_rate: Fraction of scenarios flagged as noisy.
        provider_value_rate: Fraction of provider-expected scenarios where value was added.
        scenarios_with_findings: Number of scenarios that produced findings.
        scenarios_quiet: Number of scenarios that produced zero findings/concerns/observations.
    """

    corpus_size: int = 0
    scores: list[ScenarioScore] = field(default_factory=list)
    all_passed: bool = True
    findings_stability_rate: float = 0.0
    decision_stability_rate: float = 0.0
    trust_boundary_rate: float = 0.0
    gate_accuracy_rate: float = 0.0
    quietness_rate: float = 0.0
    noise_rate: float = 0.0
    provider_value_rate: float = 0.0
    scenarios_with_findings: int = 0
    scenarios_quiet: int = 0


# ------------------------------------------------------------------
# Scorecard builder
# ------------------------------------------------------------------


def _safe_rate(numerator: int, denominator: int) -> float:
    """Compute rate, returning 1.0 when denominator is 0."""
    if denominator == 0:
        return 1.0
    return numerator / denominator


def _score_scenario(
    scenario: ValidationScenario,
    result: ValidationResult,
    comparison: ComparisonResult | None,
) -> ScenarioScore:
    """Build a ScenarioScore from run results and optional comparison."""
    analysis = result.analysis
    scan = result.scan_result

    is_low_signal = "low-signal" in scenario.tags
    expects_no_findings = "no-findings" in scenario.tags
    expects_gate_skip = "gate-skip" in scenario.tags
    expects_provider_value = scenario.provider_value_expected is True

    findings_count = len(analysis.findings)
    concern_count = len(analysis.concerns)
    observation_count = len(analysis.observations)
    notes_count = len(analysis.provider_notes)

    # Quietness: low-signal scenarios should produce zero output
    quiet_when_expected = None
    if is_low_signal or expects_no_findings:
        quiet_when_expected = (
            findings_count == 0
            and concern_count == 0
            and observation_count == 0
            and notes_count == 0
        )

    # Gate correctness
    gate_correct = None
    gate_decision = analysis.trace.provider_gate_decision
    if scenario.expected.provider_gate_invoked is True:
        gate_correct = gate_decision == "invoked"
    elif scenario.expected.provider_gate_invoked is False:
        gate_correct = gate_decision in ("skipped", "disabled", "unavailable")

    # Noise detection: unexpected observations/notes on low-signal
    noisy = False
    if is_low_signal and (concern_count > 0 or observation_count > 0 or notes_count > 0):
        noisy = True

    # Comparison-derived signals
    findings_stable = None
    decision_stable = None
    provider_added_value = None
    if comparison is not None:
        findings_stable = comparison.findings_stable
        decision_stable = comparison.decision_stable
        if expects_provider_value:
            provider_added_value = (
                comparison.provider_added_observations
                or comparison.provider_added_notes
            )

    return ScenarioScore(
        scenario_id=scenario.id,
        tags=list(scenario.tags),
        passed=result.passed,
        findings_count=findings_count,
        concern_count=concern_count,
        observation_count=observation_count,
        provider_notes_count=notes_count,
        gate_decision=gate_decision,
        decision=scan.decision.value,
        risk_score=scan.risk_score,
        findings_stable=findings_stable,
        decision_stable=decision_stable,
        provider_added_value=provider_added_value,
        gate_correct=gate_correct,
        trust_boundary_ok=comparison.trust_boundaries_held if comparison else True,
        quiet_when_expected=quiet_when_expected,
        noisy=noisy,
    )


def build_scorecard(
    scenarios: list[ValidationScenario],
    *,
    run_comparisons: bool = True,
) -> EvaluationScorecard:
    """Build an evaluation scorecard for a corpus of scenarios.

    Args:
        scenarios: List of scenarios to evaluate.
        run_comparisons: Whether to run disabled/mock comparisons.
            Default ``True``.

    Returns:
        An ``EvaluationScorecard`` with per-scenario scores and
        aggregate rates.
    """
    scores: list[ScenarioScore] = []

    for scenario in scenarios:
        result = run_scenario(scenario)
        comparison = run_comparison(scenario) if run_comparisons else None
        score = _score_scenario(scenario, result, comparison)
        scores.append(score)

    # Aggregate rates
    n = len(scores)
    all_passed = all(s.passed for s in scores)

    # Stability rates (only for scenarios with comparison)
    compared = [s for s in scores if s.findings_stable is not None]
    findings_stable_count = sum(1 for s in compared if s.findings_stable)
    decision_stable_count = sum(1 for s in compared if s.decision_stable)

    # Trust boundary
    trust_ok_count = sum(1 for s in scores if s.trust_boundary_ok)

    # Gate accuracy (only for scenarios with gate expectations)
    gate_assessed = [s for s in scores if s.gate_correct is not None]
    gate_correct_count = sum(1 for s in gate_assessed if s.gate_correct)

    # Quietness (only for scenarios expected to be quiet)
    quiet_assessed = [s for s in scores if s.quiet_when_expected is not None]
    quiet_count = sum(1 for s in quiet_assessed if s.quiet_when_expected)

    # Noise
    noisy_count = sum(1 for s in scores if s.noisy)

    # Provider value
    provider_assessed = [s for s in scores if s.provider_added_value is not None]
    provider_value_count = sum(1 for s in provider_assessed if s.provider_added_value)

    # Counts
    with_findings = sum(1 for s in scores if s.findings_count > 0)
    quiet_total = sum(
        1 for s in scores
        if s.findings_count == 0 and s.concern_count == 0 and s.observation_count == 0
    )

    return EvaluationScorecard(
        corpus_size=n,
        scores=scores,
        all_passed=all_passed,
        findings_stability_rate=_safe_rate(findings_stable_count, len(compared)),
        decision_stability_rate=_safe_rate(decision_stable_count, len(compared)),
        trust_boundary_rate=_safe_rate(trust_ok_count, n),
        gate_accuracy_rate=_safe_rate(gate_correct_count, len(gate_assessed)),
        quietness_rate=_safe_rate(quiet_count, len(quiet_assessed)),
        noise_rate=_safe_rate(noisy_count, n),
        provider_value_rate=_safe_rate(provider_value_count, len(provider_assessed)),
        scenarios_with_findings=with_findings,
        scenarios_quiet=quiet_total,
    )


# ------------------------------------------------------------------
# Scorecard formatter
# ------------------------------------------------------------------


def _pct(rate: float) -> str:
    """Format a rate as a percentage string."""
    return f"{rate * 100:.0f}%"


def _bool_str(val: bool | None) -> str:
    """Format a boolean or None as a display string."""
    if val is None:
        return "—"
    return "✓" if val else "✗"


def format_scorecard(sc: EvaluationScorecard) -> str:
    """Format an EvaluationScorecard as a human-readable summary.

    Returns a multi-line string suitable for terminal output or
    markdown rendering.
    """
    lines: list[str] = []

    lines.append(f"Evaluation Scorecard ({sc.corpus_size} scenarios)")
    lines.append("=" * 70)
    lines.append("")

    # Summary rates
    lines.append("Aggregate Rates:")
    lines.append(f"  All passed:            {_bool_str(sc.all_passed)}")
    lines.append(f"  Findings stability:    {_pct(sc.findings_stability_rate)}")
    lines.append(f"  Decision stability:    {_pct(sc.decision_stability_rate)}")
    lines.append(f"  Trust boundaries:      {_pct(sc.trust_boundary_rate)}")
    lines.append(f"  Gate accuracy:         {_pct(sc.gate_accuracy_rate)}")
    lines.append(f"  Quietness:             {_pct(sc.quietness_rate)}")
    lines.append(f"  Noise rate:            {_pct(sc.noise_rate)}")
    lines.append(f"  Provider value-add:    {_pct(sc.provider_value_rate)}")
    lines.append(f"  With findings:         {sc.scenarios_with_findings}/{sc.corpus_size}")
    lines.append(f"  Quiet scenarios:       {sc.scenarios_quiet}/{sc.corpus_size}")
    lines.append("")

    # Per-scenario table
    hdr = (
        f"{'ID':<38} {'Pass':<5} {'Find':<5} {'Conc':<5} {'Obs':<4} "
        f"{'Notes':<6} {'Gate':<10} {'Stable':<7} {'Trust':<6} {'Quiet':<6} {'Noise':<6}"
    )
    lines.append("Per-Scenario Detail:")
    lines.append(hdr)
    lines.append("-" * len(hdr))

    for s in sc.scores:
        lines.append(
            f"{s.scenario_id:<38} "
            f"{_bool_str(s.passed):<5} "
            f"{s.findings_count:<5} "
            f"{s.concern_count:<5} "
            f"{s.observation_count:<4} "
            f"{s.provider_notes_count:<6} "
            f"{s.gate_decision:<10} "
            f"{_bool_str(s.findings_stable):<7} "
            f"{_bool_str(s.trust_boundary_ok):<6} "
            f"{_bool_str(s.quiet_when_expected):<6} "
            f"{_bool_str(not s.noisy):<6}"
        )

    lines.append("")
    lines.append("Legend: ✓ = yes/ok, ✗ = no/issue, — = not assessed")
    lines.append("")
    lines.append(
        "This scorecard is a practical tuning aid, not a scientific benchmark."
    )

    return "\n".join(lines)
