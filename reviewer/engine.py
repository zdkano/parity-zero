"""Analysis engine for parity-zero.

Coordinates the Phase 1 reviewer flow described in ADR-004:

  1. Deterministic checks  — narrow high-signal guardrails (checks.py).
  2. Reasoning layer        — contextual LLM review stub (reasoning.py).

The engine merges results from both strategies, deduplicates findings,
derives a deterministic decision/risk_score, and returns a structured
AnalysisResult.

The engine accepts PRContent (ADR-011) as its input, decoupling the
analysis interface from raw ``dict[str, str]``.  Internally it converts
to dicts for modules that still use that interface.

Decision / risk_score derivation rule (Phase 1 MVP — ADR-012):
  - Each finding contributes a weight based on severity:
      high = 25, medium = 15, low = 5
  - risk_score = min(sum of weights, 100)
  - decision  = PASS  if risk_score < 25
              = WARN  if risk_score >= 25
  BLOCK is not used in Phase 1 unless explicitly warranted.

  Note: this scoring model is intentionally coarse and temporary.
  Later iterations may refine severity weighting, confidence influence,
  repeated low-severity accumulation, WARN vs BLOCK distinction, and
  policy-mode-aware decisioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.findings import Decision, Finding, Severity
from reviewer.checks import run_deterministic_checks
from reviewer.models import PRContent
from reviewer.reasoning import run_reasoning

# Severity weights used for risk_score derivation.
_SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.HIGH: 25,
    Severity.MEDIUM: 15,
    Severity.LOW: 5,
}

# risk_score threshold above which the decision becomes WARN.
_WARN_THRESHOLD = 25


@dataclass
class AnalysisResult:
    """Combined output from all analysis strategies.

    Attributes:
        findings: Deduplicated list of findings from all strategies.
        reasoning_notes: Contextual notes from the reasoning layer.
            Informational only — they do not affect decision or risk_score.
    """

    findings: list[Finding] = field(default_factory=list)
    reasoning_notes: list[str] = field(default_factory=list)


def analyse(pr_content: PRContent | dict[str, str]) -> AnalysisResult:
    """Run all analysis strategies against the changed file contents.

    Args:
        pr_content: A PRContent instance (preferred) or a legacy
            ``{path: content}`` dict.  Dicts are automatically converted
            to PRContent for backward compatibility.

    Returns:
        An AnalysisResult with combined findings and reasoning notes.
    """
    if isinstance(pr_content, dict):
        pr_content = PRContent.from_dict(pr_content)

    file_contents = pr_content.to_dict()
    findings: list[Finding] = []

    findings.extend(run_deterministic_checks(file_contents))

    reasoning_result = run_reasoning(file_contents)
    findings.extend(reasoning_result.findings)

    return AnalysisResult(
        findings=_deduplicate(findings),
        reasoning_notes=reasoning_result.notes,
    )


def derive_decision_and_risk(findings: list[Finding]) -> tuple[Decision, int]:
    """Derive a deterministic decision and risk_score from findings.

    Uses the Phase 1 MVP rule documented at module level.

    Args:
        findings: The list of findings to evaluate.

    Returns:
        A (decision, risk_score) tuple.
    """
    if not findings:
        return Decision.PASS, 0

    risk_score = min(
        sum(_SEVERITY_WEIGHTS.get(f.severity, 0) for f in findings),
        100,
    )

    decision = Decision.WARN if risk_score >= _WARN_THRESHOLD else Decision.PASS
    return decision, risk_score


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """Remove duplicate findings based on id."""
    seen: set[str] = set()
    unique: list[Finding] = []
    for f in findings:
        if f.id not in seen:
            seen.add(f.id)
            unique.append(f)
    return unique
