"""Analysis engine for parity-zero.

Coordinates the two analysis strategies described in ADR-004:

  1. Deterministic checks  — high-confidence pattern matching (checks.py).
  2. Reasoning layer        — LLM-based contextual analysis (reasoning.py).

The engine merges results from both strategies, deduplicates, and returns
a flat list of Finding objects.

Phase 1: both subsystems are stubs.  The engine wiring is in place so that
real detection logic can be added incrementally without restructuring.
"""

from __future__ import annotations

from schemas.findings import Finding
from reviewer.checks import run_deterministic_checks
from reviewer.reasoning import run_reasoning


def analyse(changed_files: list[str]) -> list[Finding]:
    """Run all analysis strategies against the changed files.

    Args:
        changed_files: Paths (repo-relative) of files changed in the PR.

    Returns:
        A combined, deduplicated list of findings.
    """
    findings: list[Finding] = []

    findings.extend(run_deterministic_checks(changed_files))
    findings.extend(run_reasoning(changed_files))

    return _deduplicate(findings)


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """Remove duplicate findings based on id.

    TODO: Consider deduplicating on (file, start_line, category) as well.
    """
    seen: set[str] = set()
    unique: list[Finding] = []
    for f in findings:
        if f.id not in seen:
            seen.add(f.id)
            unique.append(f)
    return unique
