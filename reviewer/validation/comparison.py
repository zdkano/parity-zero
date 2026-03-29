"""Provider comparison for evaluation scenarios (ADR-038).

Runs the same ``ValidationScenario`` across multiple provider modes and
produces a structured ``ComparisonResult`` capturing meaningful
differences.  The immediate implementation supports ``disabled`` and
``mock`` modes — no live credentials are required.

The comparison layer helps answer questions like:
- Did provider-backed reasoning add observations?
- Did it add only noise?
- Did gate behavior differ appropriately?
- Did output length / section count increase?
- Were trust boundaries preserved in both modes?

This is intentionally lightweight — not a benchmark platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from reviewer.engine import derive_decision_and_risk
from reviewer.validation.runner import ValidationResult, run_scenario
from reviewer.validation.scenario import ValidationScenario, ExpectedBehavior


# ------------------------------------------------------------------
# Comparison types
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ModeResult:
    """Summary of a single scenario run in a specific provider mode."""

    mode: str
    findings_count: int
    finding_categories: list[str]
    concern_count: int
    observation_count: int
    provider_notes_count: int
    gate_decision: str
    decision: str
    risk_score: int
    markdown_length: int
    markdown_section_count: int
    trust_boundary_ok: bool


@dataclass
class ComparisonResult:
    """Result of comparing one scenario across provider modes.

    Attributes:
        scenario_id: The scenario that was compared.
        modes: Provider modes that were compared.
        results: Per-mode structured summaries.
        validation_results: Per-mode full ValidationResult (for deep inspection).
        findings_stable: Whether deterministic findings are the same across modes.
        decision_stable: Whether decision/risk are the same across modes.
        provider_added_observations: Whether mock mode added observations beyond disabled.
        provider_added_notes: Whether mock mode produced provider notes.
        gate_differed: Whether the gate decision differed across modes.
        trust_boundaries_held: Whether trust boundaries held in all modes.
    """

    scenario_id: str
    modes: list[str] = field(default_factory=list)
    results: dict[str, ModeResult] = field(default_factory=dict)
    validation_results: dict[str, ValidationResult] = field(default_factory=dict)
    findings_stable: bool = True
    decision_stable: bool = True
    provider_added_observations: bool = False
    provider_added_notes: bool = False
    gate_differed: bool = False
    trust_boundaries_held: bool = True


# ------------------------------------------------------------------
# Comparison runner
# ------------------------------------------------------------------


def _summarize_mode(
    mode: str, vr: ValidationResult,
) -> ModeResult:
    """Extract a structured summary from a ValidationResult."""
    analysis = vr.analysis
    scan = vr.scan_result
    md = vr.markdown

    findings_count = len(analysis.findings)
    categories = sorted({f.category.value for f in analysis.findings})
    concern_count = len(analysis.concerns)
    obs_count = len(analysis.observations)
    notes_count = len(analysis.provider_notes)
    gate = analysis.trace.provider_gate_decision
    section_count = md.count("\n## ") + md.count("\n### ")

    # Trust boundary: decision must match findings-only derivation
    expected_decision, expected_risk = derive_decision_and_risk(analysis.findings)
    trust_ok = (
        scan.decision == expected_decision
        and scan.risk_score == expected_risk
        and all(getattr(f, "source", None) != "provider" for f in analysis.findings)
    )

    return ModeResult(
        mode=mode,
        findings_count=findings_count,
        finding_categories=categories,
        concern_count=concern_count,
        observation_count=obs_count,
        provider_notes_count=notes_count,
        gate_decision=gate,
        decision=scan.decision.value,
        risk_score=scan.risk_score,
        markdown_length=len(md),
        markdown_section_count=section_count,
        trust_boundary_ok=trust_ok,
    )


def run_comparison(
    scenario: ValidationScenario,
    modes: list[Literal["disabled", "mock"]] | None = None,
) -> ComparisonResult:
    """Run a scenario across provider modes and compare results.

    Args:
        scenario: The scenario to compare.
        modes: Provider modes to compare.  Defaults to ``["disabled", "mock"]``.

    Returns:
        A ``ComparisonResult`` with per-mode summaries and cross-mode diffs.
    """
    if modes is None:
        modes = ["disabled", "mock"]

    comparison = ComparisonResult(
        scenario_id=scenario.id,
        modes=list(modes),
    )

    # Run each mode
    for mode in modes:
        variant = ValidationScenario(
            id=scenario.id,
            description=scenario.description,
            changed_files=scenario.changed_files,
            baseline_profile=scenario.baseline_profile,
            memory=scenario.memory,
            provider_mode=mode,
            tags=scenario.tags,
            security_focus=scenario.security_focus,
            provider_value_expected=scenario.provider_value_expected,
            # Use a relaxed expected behavior for comparison runs —
            # we evaluate cross-mode diffs, not per-mode assertions.
            expected=ExpectedBehavior(no_trust_boundary_violations=True),
        )
        vr = run_scenario(variant)
        comparison.validation_results[mode] = vr
        comparison.results[mode] = _summarize_mode(mode, vr)

    # Cross-mode analysis
    mode_summaries = list(comparison.results.values())

    # Findings stability: deterministic findings should be the same
    if len(mode_summaries) >= 2:
        cats_0 = set(mode_summaries[0].finding_categories)
        counts_0 = mode_summaries[0].findings_count
        for ms in mode_summaries[1:]:
            if set(ms.finding_categories) != cats_0 or ms.findings_count != counts_0:
                comparison.findings_stable = False

    # Decision stability
    if len(mode_summaries) >= 2:
        dec_0 = (mode_summaries[0].decision, mode_summaries[0].risk_score)
        for ms in mode_summaries[1:]:
            if (ms.decision, ms.risk_score) != dec_0:
                comparison.decision_stable = False

    # Provider value detection
    disabled_summary = comparison.results.get("disabled")
    mock_summary = comparison.results.get("mock")
    if disabled_summary and mock_summary:
        if mock_summary.observation_count > disabled_summary.observation_count:
            comparison.provider_added_observations = True
        if mock_summary.provider_notes_count > 0:
            comparison.provider_added_notes = True

    # Gate difference
    gates = [ms.gate_decision for ms in mode_summaries]
    if len(set(gates)) > 1:
        comparison.gate_differed = True

    # Trust boundaries
    comparison.trust_boundaries_held = all(
        ms.trust_boundary_ok for ms in mode_summaries
    )

    return comparison


def format_comparison_summary(comp: ComparisonResult) -> str:
    """Format a ComparisonResult as a concise human-readable summary."""
    lines = [
        f"Comparison: {comp.scenario_id}",
        f"Modes: {', '.join(comp.modes)}",
        "",
    ]

    for mode, ms in comp.results.items():
        lines.append(f"  [{mode}]")
        lines.append(f"    findings: {ms.findings_count} ({', '.join(ms.finding_categories) or 'none'})")
        lines.append(f"    concerns: {ms.concern_count}, observations: {ms.observation_count}")
        lines.append(f"    provider_notes: {ms.provider_notes_count}")
        lines.append(f"    gate: {ms.gate_decision}")
        lines.append(f"    decision: {ms.decision} (risk={ms.risk_score})")
        lines.append(f"    markdown: {ms.markdown_length} chars, {ms.markdown_section_count} sections")
        lines.append(f"    trust_boundary: {'ok' if ms.trust_boundary_ok else 'VIOLATED'}")
        lines.append("")

    lines.append("Cross-mode:")
    lines.append(f"  findings_stable: {comp.findings_stable}")
    lines.append(f"  decision_stable: {comp.decision_stable}")
    lines.append(f"  provider_added_observations: {comp.provider_added_observations}")
    lines.append(f"  provider_added_notes: {comp.provider_added_notes}")
    lines.append(f"  gate_differed: {comp.gate_differed}")
    lines.append(f"  trust_boundaries_held: {comp.trust_boundaries_held}")

    return "\n".join(lines)
