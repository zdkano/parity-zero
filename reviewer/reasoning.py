"""LLM review layer for parity-zero.

This module provides the contextual, LLM-based review path.  Deterministic
checks remain narrow supporting guardrails; the reasoning layer handles:

  - contextual summarisation of code changes
  - ambiguous logic review (future)
  - optional additive reviewer notes
  - prioritisation support

See ADR-004 and architecture.md § Reasoning Layer.

Phase 1: this is a structured stub.  LLM integration will be added in a
subsequent iteration.  The stub makes the layer's responsibilities clear
and provides a realistic interface for the engine to consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.findings import Finding


@dataclass
class ReasoningResult:
    """Structured output from the reasoning layer.

    Attributes:
        findings: Low-to-medium confidence findings surfaced by contextual
            review.  Empty in the Phase 1 stub.
        notes: Additive reviewer notes — contextual observations that do
            not rise to the level of a finding but may be useful in the
            PR summary.  These are informational only and do not affect
            decision or risk_score.
    """

    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_reasoning(file_contents: dict[str, str]) -> ReasoningResult:
    """Run LLM-based reasoning analysis against the changed file contents.

    In Phase 1 this is a stub that returns an empty result with a
    contextual note.  Future iterations will integrate an LLM provider
    to perform contextual analysis of the diff.

    Args:
        file_contents: Mapping of repo-relative file paths to their text
            content.

    Returns:
        A ReasoningResult with stub findings and notes.
    """
    notes: list[str] = []

    if file_contents:
        file_count = len(file_contents)
        notes.append(
            f"Reasoning layer reviewed {file_count} file(s). "
            f"LLM-based contextual analysis is not yet connected — "
            f"deterministic checks only."
        )
    else:
        notes.append(
            "No changed files provided for reasoning review."
        )

    return ReasoningResult(findings=[], notes=notes)
