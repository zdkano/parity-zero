"""LLM reasoning layer for parity-zero.

This module provides contextual, LLM-based analysis of changed code.
It complements the deterministic checks (checks.py) and is used for:

  - contextual interpretation of code changes
  - summarisation and developer-friendly explanation
  - ambiguous logic review
  - prioritisation support

See ADR-004 and architecture.md § Reasoning Layer.

The reasoning layer should *support* the reviewer, not define the entire
truth of the system.  Findings from this layer should clearly indicate
their confidence level.

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
