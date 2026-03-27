"""Deterministic security checks for parity-zero.

This module implements high-confidence, pattern-based checks that do not
require LLM reasoning.  See ADR-004 and architecture.md § Deterministic Checks.

Examples of future checks:
  - hardcoded secrets patterns
  - obvious missing auth middleware
  - dangerous input handling patterns
  - insecure configuration defaults

Phase 1: this is a placeholder.  Individual check functions will be added
here as the reviewer matures.
"""

from __future__ import annotations

from schemas.findings import Finding


def run_deterministic_checks(changed_files: list[str]) -> list[Finding]:
    """Run all deterministic checks against the changed files.

    Args:
        changed_files: Paths (repo-relative) of files changed in the PR.

    Returns:
        Findings from deterministic analysis.  Empty in the initial scaffold.
    """
    # TODO: Implement individual check functions and register them here.
    return []
