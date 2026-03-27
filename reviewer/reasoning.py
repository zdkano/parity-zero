"""LLM review layer for parity-zero.

This module provides the primary Phase 1 analysis path: contextual,
LLM-based review of changed code.  Deterministic checks, where present,
remain narrow supporting guardrails rather than the core product value.

The reasoning layer is used for:

  - contextual interpretation of code changes
  - summarisation and developer-friendly explanation
  - ambiguous logic review
  - prioritisation support

See ADR-004 and architecture.md § Reasoning Layer.

In Phase 1, the LLM reviewer is the MVP.  Findings from this layer should
clearly indicate their confidence level and stay focused on practical PR
review rather than broad scanner-style coverage.

Phase 1: this is a placeholder.  LLM integration will be added in a
subsequent iteration.
"""

from __future__ import annotations

from schemas.findings import Finding


def run_reasoning(changed_files: list[str]) -> list[Finding]:
    """Run LLM-based reasoning analysis against the changed files.

    Args:
        changed_files: Paths (repo-relative) of files changed in the PR.

    Returns:
        Findings from reasoning analysis.  Empty in the initial scaffold.
    """
    # TODO: Integrate LLM provider and implement contextual analysis.
    return []
