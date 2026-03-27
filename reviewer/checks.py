"""Narrow deterministic guardrails for parity-zero.

This module is limited to high-confidence checks that support the reviewer
without turning parity-zero into another SAST tool.  See ADR-004 and
architecture.md § Deterministic Checks.

Examples of future guardrails:
  - obvious missing auth middleware in known patterns
  - dangerous input handling that is trivial to spot
  - insecure configuration defaults in touched code

Phase 1: this is a placeholder.  Any future checks should stay narrow,
high-signal, and secondary to the LLM reviewer.
"""

from __future__ import annotations

from schemas.findings import Finding


def run_deterministic_checks(changed_files: list[str]) -> list[Finding]:
    """Run the narrow deterministic guardrails against the changed files.

    Args:
        changed_files: Paths (repo-relative) of files changed in the PR.

    Returns:
        Findings from supplemental deterministic analysis.  Empty in the
        initial scaffold.
    """
    # TODO: Implement a small set of high-signal guardrails here.
    return []
