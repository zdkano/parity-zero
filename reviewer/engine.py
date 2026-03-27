"""Analysis engine for parity-zero.

Coordinates the Phase 1 reviewer flow described in ADR-004:

  1. Reasoning layer        — LLM-led contextual review (reasoning.py).
  2. Deterministic checks  — narrow supporting guardrails (checks.py).

The engine merges results from both strategies, deduplicates, and returns
a flat list of Finding objects.

Phase 1 keeps the LLM reviewer as the MVP.  Deterministic checks remain
supporting placeholders so parity-zero stays focused on AI review rather
than broad scanner-style coverage.
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
