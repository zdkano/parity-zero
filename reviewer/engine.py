"""Contextual security review engine for parity-zero.

Coordinates the reviewer flow described in the corrected architecture
(ADR-013, ADR-014, ADR-018):

  1. **Contextual review**       — the primary review path, consuming PR
     delta + baseline profile + review memory to reason about security
     implications (reasoning.py).
  2. **Deterministic support**   — narrow high-signal guardrails providing
     supporting signals to the contextual review (checks.py).

The engine merges results from both strategies, deduplicates findings,
derives a deterministic decision/risk_score, and returns a structured
AnalysisResult.

The engine accepts ``PullRequestContext`` (ADR-018) as its preferred input,
with backward compatibility for ``PRContent`` (ADR-011) and raw
``dict[str, str]``.

Decision / risk_score derivation rule (Phase 1 MVP — ADR-012, ADR-017):
  - Each finding contributes a weight based on severity:
      high = 25, medium = 15, low = 5
  - risk_score = min(sum of weights, 100)
  - decision  = PASS  if risk_score < 25
              = WARN  if risk_score >= 25
  BLOCK is not used in Phase 1 unless explicitly warranted.

  Note: this scoring model is intentionally coarse and temporary.
  Later iterations may refine severity weighting, confidence influence,
  repeated low-severity accumulation, WARN vs BLOCK distinction,
  baseline-aware scoring, and policy-mode-aware decisioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.findings import Decision, Finding, Severity
from reviewer.checks import run_deterministic_checks
from reviewer.models import PRContent, PullRequestContext
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


def analyse(
    pr_input: PullRequestContext | PRContent | dict[str, str],
) -> AnalysisResult:
    """Run all analysis strategies against the changed file contents.

    The engine coordinates two analysis strategies:

    1. **Deterministic support checks** — narrow, high-confidence
       guardrails that catch obvious issues (supporting signal layer).
    2. **Contextual review** — the primary review path that will
       eventually reason over PR delta + baseline profile + review
       memory (currently a structured stub).

    Args:
        pr_input: A ``PullRequestContext`` (preferred), ``PRContent``,
            or a legacy ``{path: content}`` dict.  Non-context inputs
            are automatically wrapped for backward compatibility.

    Returns:
        An AnalysisResult with combined findings and reasoning notes.
    """
    # -- Normalise input to PullRequestContext --
    if isinstance(pr_input, dict):
        ctx = PullRequestContext.from_dict(pr_input)
    elif isinstance(pr_input, PRContent):
        ctx = PullRequestContext.from_pr_content(pr_input)
    else:
        ctx = pr_input

    file_contents = ctx.pr_content.to_dict()
    findings: list[Finding] = []

    # -- Deterministic support layer (ADR-013) --
    findings.extend(run_deterministic_checks(file_contents))

    # -- Contextual review — primary review path (ADR-014) --
    # Phase 1: the reasoning layer is a structured stub.  When LLM
    # integration is added, it will receive the full PullRequestContext
    # (including baseline profile and memory) rather than raw dicts.
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
