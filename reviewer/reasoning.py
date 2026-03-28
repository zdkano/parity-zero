"""Contextual security review layer for parity-zero.

This module provides the **primary review path** — contextual, reasoning-based
security analysis that will eventually consume:

  - PR delta (changed files and their content)
  - baseline repository security profile (ADR-015)
  - deterministic support signals (ADR-013)
  - review memory and prior findings themes (ADR-016)
  - policy/intent context (later phases)

It produces contextual findings and reviewer notes that form the core of
parity-zero's security review value.

This is **not** a thin wrapper over deterministic checks.  The intended role
is to reason about security implications like a security engineer who
understands the repository context — see ADR-014.

See also: architecture.md § Reasoning Layer (Contextual Review).

Phase 1: this is a structured stub.  LLM integration will be added in a
subsequent iteration.  The stub makes the layer's responsibilities and
interface clear and provides a realistic contract for the engine to consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.findings import Finding


@dataclass
class ReasoningResult:
    """Structured output from the contextual review layer.

    Attributes:
        findings: Contextual findings surfaced by reasoning-based review.
            Empty in the Phase 1 stub.  When LLM integration is added,
            these will carry confidence-weighted assessments with
            reasoning context.
        notes: Contextual reviewer notes — observations about the PR
            delta that do not rise to the level of a finding but may be
            useful in the PR summary.  These are informational only and
            do not affect decision or risk_score.
    """

    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_reasoning(file_contents: dict[str, str]) -> ReasoningResult:
    """Run contextual security review against the changed file contents.

    This is the primary review path for parity-zero.  When fully
    implemented, it will:
    - analyse the PR delta in the context of the repository baseline
    - consider review memory for recurring patterns
    - reason about architectural and logic-level security implications
    - produce confidence-weighted findings with explanations

    Phase 1: returns an empty result with a contextual note.  Future
    iterations will integrate an LLM provider and consume the full
    ``PullRequestContext`` (including baseline profile and review memory)
    rather than raw dicts.

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
            f"Contextual review examined {file_count} file(s). "
            f"LLM-based reasoning is not yet connected — "
            f"deterministic support checks only in Phase 1."
        )
    else:
        notes.append(
            "No changed files provided for contextual review."
        )

    return ReasoningResult(findings=[], notes=notes)
