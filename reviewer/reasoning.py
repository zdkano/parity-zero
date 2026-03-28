"""Contextual security review layer for parity-zero.

This module provides the **primary review path** — contextual, reasoning-based
security analysis that consumes:

  - PR delta (changed files and their content)
  - baseline repository security profile (ADR-015)
  - review memory and prior findings themes (ADR-016)
  - structured review plan (ADR-021)
  - deterministic support signals (ADR-013, consumed via engine)
  - policy/intent context (later phases)

It produces contextual findings and reviewer notes that form the core of
parity-zero's security review value.

This is **not** a thin wrapper over deterministic checks.  The intended role
is to reason about security implications like a security engineer who
understands the repository context — see ADR-014.

See also: architecture.md § Reasoning Layer (Contextual Review).

Phase 1 implementation: baseline-aware and memory-aware contextual review
notes, now driven by a structured ``ReviewPlan`` (ADR-021).  The planner
derives focus areas from ``PullRequestContext`` and the reasoning layer
translates plan focus into contextual notes.  Per-file review observations
are derived from the ReviewBundle (ADR-024).  LLM integration will be
added in a subsequent iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.findings import Finding
from reviewer.models import PullRequestContext, RepoSecurityProfile, ReviewBundle, ReviewConcern, ReviewMemory, ReviewObservation, ReviewPlan

# Canonical path analysis helpers live in planner.py (ADR-021).
# Re-exported here for backward compatibility with existing callers/tests.
from reviewer.planner import (  # noqa: F401
    sensitive_path_overlap as _sensitive_path_overlap,
    auth_path_overlap as _auth_path_overlap,
    infer_path_categories as _infer_path_categories,
    relevant_memory_entries as _relevant_memory_entries,
    build_review_plan,
    generate_concerns,
)
from reviewer.bundle import build_review_bundle
from reviewer.observations import generate_observations


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
        concerns: Plan-informed review concerns — areas that may deserve
            closer security attention based on context.  Distinct from
            findings; do not affect scoring.  See ADR-022.
        observations: Per-file review observations derived from ReviewBundle
            items.  Each observation explains why a specific file deserves
            scrutiny.  Distinct from concerns (which are plan-level) and
            findings (which claim issues).  See ADR-024.
        bundle: Structured review evidence gathered from PR delta,
            baseline, memory, and review plan.  Carries per-file context
            and review reasons.  Internal only — does not appear in the
            JSON contract.  See ADR-023.
    """

    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    concerns: list[ReviewConcern] = field(default_factory=list)
    observations: list[ReviewObservation] = field(default_factory=list)
    bundle: ReviewBundle | None = None


def run_reasoning(
    ctx: PullRequestContext | dict[str, str],
    plan: ReviewPlan | None = None,
) -> ReasoningResult:
    """Run contextual security review against changed files with repo context.

    ``PullRequestContext`` is the **canonical input** (ADR-018, ADR-019).
    A raw ``dict[str, str]`` is accepted for backward compatibility but
    is automatically wrapped — callers should migrate to
    ``PullRequestContext``.

    When a ``ReviewPlan`` is provided (ADR-021), contextual notes are
    derived from the structured plan rather than ad-hoc overlap checks.
    This ensures that review attention is driven by a single, explicit
    planning step.

    Phase 1 behaviour:
    - produces contextual notes from the review plan or baseline overlap
    - surfaces relevant review memory as historical awareness
    - does not yet produce LLM-generated findings
    - notes are informational and do not affect decision or risk_score

    Args:
        ctx: A ``PullRequestContext`` (preferred) or a legacy
            ``{path: content}`` dict.
        plan: An optional ``ReviewPlan`` that structures review focus.
            When provided, notes are derived from the plan.

    Returns:
        A ReasoningResult with contextual notes and (currently empty)
        findings.
    """
    # -- Normalise input --
    if isinstance(ctx, dict):
        ctx = PullRequestContext.from_dict(ctx)

    file_contents = ctx.pr_content.to_dict()
    notes: list[str] = []

    if not file_contents:
        notes.append("No changed files provided for contextual review.")
        return ReasoningResult(findings=[], notes=notes)

    file_count = len(file_contents)
    notes.append(
        f"Contextual review examined {file_count} file(s)."
    )

    # -- Plan-driven contextual notes (ADR-021) --
    # -- Plan-driven contextual concerns (ADR-022) --
    # -- Review bundle assembly (ADR-023) --
    # -- Per-file review observations (ADR-024) --
    concerns: list[ReviewConcern] = []
    observations: list[ReviewObservation] = []
    bundle: ReviewBundle | None = None
    if plan is not None:
        _add_plan_notes(notes, plan)
        concerns = generate_concerns(plan, ctx)
        bundle = build_review_bundle(ctx, plan)
        observations = generate_observations(bundle)
    else:
        # Legacy path: derive notes directly from context overlap
        changed_paths = ctx.pr_content.paths
        if ctx.has_baseline and ctx.baseline_profile is not None:
            _add_baseline_notes(notes, changed_paths, ctx.baseline_profile)
        if ctx.has_memory and ctx.memory is not None:
            _add_memory_notes(notes, changed_paths, ctx.memory)

    return ReasoningResult(
        findings=[], notes=notes, concerns=concerns,
        observations=observations, bundle=bundle,
    )


# ======================================================================
# Plan-driven contextual notes (ADR-021)
# ======================================================================


def _add_plan_notes(notes: list[str], plan: ReviewPlan) -> None:
    """Generate contextual notes from a structured ReviewPlan.

    Translates the plan's focus areas, flags, and guidance into
    informational review notes.  This replaces ad-hoc overlap checks
    when a plan is available.
    """
    # -- Sensitive path notes --
    if plan.sensitive_paths_touched:
        paths_str = ", ".join(f"`{p}`" for p in plan.sensitive_paths_touched[:5])
        notes.append(
            f"This PR touches sensitive path(s): {paths_str}. "
            f"Changes in these areas warrant closer security review."
        )

    # -- Auth path notes --
    if plan.auth_paths_touched:
        paths_str = ", ".join(f"`{p}`" for p in plan.auth_paths_touched[:5])
        notes.append(
            f"This PR modifies authentication/authorisation-related path(s): "
            f"{paths_str}. "
            f"Verify that access control logic remains correct."
        )

    # -- Auth pattern context --
    if plan.auth_pattern_context:
        patterns_str = ", ".join(plan.auth_pattern_context[:4])
        notes.append(
            f"Repository baseline indicates auth-related patterns: "
            f"{patterns_str}. "
            f"Review changes for consistency with existing auth mechanisms."
        )

    # -- Framework context --
    if plan.framework_context:
        frameworks_str = ", ".join(plan.framework_context[:4])
        notes.append(
            f"Repository uses: {frameworks_str}. "
            f"Review considers framework-specific security conventions."
        )

    # -- Focus areas summary --
    if plan.focus_areas:
        areas_str = ", ".join(plan.focus_areas)
        notes.append(
            f"Review plan focus areas: {areas_str}."
        )

    # -- Memory context --
    if plan.relevant_memory_categories:
        cats_str = ", ".join(plan.relevant_memory_categories)
        notes.append(
            f"Review memory includes prior concerns in: {cats_str}. "
            f"These recurring themes are noted as historical context."
        )

    # -- Review flags summary --
    if plan.review_flags:
        flags_str = ", ".join(plan.review_flags)
        notes.append(
            f"Review flags: {flags_str}."
        )


# ======================================================================
# Baseline-aware contextual review (legacy path, used when no plan)
# ======================================================================


def _add_baseline_notes(
    notes: list[str],
    changed_paths: list[str],
    profile: RepoSecurityProfile,
) -> None:
    """Add contextual notes informed by the repository baseline profile.

    Checks for:
    - overlap between changed paths and baseline sensitive paths
    - overlap between changed paths and auth-related path segments
    - framework/language context that shapes review interpretation
    - auth patterns detected in the repo baseline
    """
    # -- Sensitive path overlap --
    sensitive_overlap = _sensitive_path_overlap(changed_paths, profile.sensitive_paths)
    if sensitive_overlap:
        paths_str = ", ".join(f"`{p}`" for p in sensitive_overlap[:5])
        notes.append(
            f"This PR touches sensitive path(s): {paths_str}. "
            f"Changes in these areas warrant closer security review."
        )

    # -- Auth-related path overlap --
    auth_paths = _auth_path_overlap(changed_paths)
    if auth_paths:
        paths_str = ", ".join(f"`{p}`" for p in auth_paths[:5])
        notes.append(
            f"This PR modifies authentication/authorisation-related path(s): "
            f"{paths_str}. "
            f"Verify that access control logic remains correct."
        )

    # -- Auth patterns from baseline --
    if profile.auth_patterns:
        patterns_str = ", ".join(profile.auth_patterns[:4])
        notes.append(
            f"Repository baseline indicates auth-related patterns: "
            f"{patterns_str}. "
            f"Review changes for consistency with existing auth mechanisms."
        )

    # -- Framework context --
    if profile.frameworks:
        frameworks_str = ", ".join(profile.frameworks[:4])
        notes.append(
            f"Repository uses: {frameworks_str}. "
            f"Review considers framework-specific security conventions."
        )

    # -- Language context (only if notable) --
    if len(profile.languages) >= 2:
        langs_str = ", ".join(profile.languages[:5])
        notes.append(
            f"Multi-language repository ({langs_str}); "
            f"cross-language security boundaries may apply."
        )


# ======================================================================
# Memory-aware contextual review (legacy path, used when no plan)
# ======================================================================


def _add_memory_notes(
    notes: list[str],
    changed_paths: list[str],
    memory: ReviewMemory,
) -> None:
    """Add contextual notes informed by review memory.

    Memory is used as **supporting context only** — it does not create
    fake certainty.  Notes mention recurring concerns when they are
    relevant to the current PR.

    Relevance is determined by:
    - memory categories that relate to changed file path areas
    - memory summaries that mention patterns relevant to the PR
    """
    if not memory.entries:
        return

    # -- Determine relevant memory categories --
    path_categories = _infer_path_categories(changed_paths)
    memory_categories = set(memory.categories())

    relevant_categories = path_categories & memory_categories
    if relevant_categories:
        cats_str = ", ".join(sorted(relevant_categories))
        notes.append(
            f"Review memory includes prior concerns in: {cats_str}. "
            f"These recurring themes are noted as historical context."
        )

    # -- Surface relevant memory entries --
    relevant_entries = _relevant_memory_entries(changed_paths, memory)
    for entry in relevant_entries[:3]:  # limit to avoid noise
        notes.append(
            f"Prior review note ({entry.category}): {entry.summary}"
        )
