"""Reasoning input assembly for parity-zero (ADR-025).

Builds a structured ``ReasoningRequest`` from the reviewer pipeline context:
- ReviewPlan (focus areas, flags, guidance)
- ReviewBundle (per-file evidence with context)
- Baseline profile (frameworks, auth patterns)
- Review memory (relevant categories and entries)
- Deterministic findings (supporting signals)
- Existing concerns and observations

The assembled request makes explicit:
- what changed
- what deserves scrutiny
- what baseline context matters
- what memory context matters
- what observations/concerns already exist

This is a **first-class part of the reviewer pipeline** — it bridges the
reviewer's structured context and the reasoning provider interface.

Phase 1: focuses on structure and clarity.  Prompt wording optimisation
is deferred to later iterations when provider integration is live.

See ADR-025 for the decision record.
"""

from __future__ import annotations

from reviewer.models import (
    PullRequestContext,
    ReviewBundle,
    ReviewConcern,
    ReviewObservation,
    ReviewPlan,
)
from reviewer.providers import ReasoningRequest
from schemas.findings import Finding


def build_reasoning_request(
    ctx: PullRequestContext,
    plan: ReviewPlan | None = None,
    bundle: ReviewBundle | None = None,
    concerns: list[ReviewConcern] | None = None,
    observations: list[ReviewObservation] | None = None,
    deterministic_findings: list[Finding] | None = None,
) -> ReasoningRequest:
    """Assemble a structured reasoning request from pipeline context.

    This is the canonical entry point for building reasoning provider
    input.  It gathers all available context into a ``ReasoningRequest``
    that a provider can consume.

    Args:
        ctx: The pull request context (changed files, baseline, memory).
        plan: Optional review plan with focus areas and flags.
        bundle: Optional review bundle with per-file evidence.
        concerns: Optional existing review concerns.
        observations: Optional existing review observations.
        deterministic_findings: Optional deterministic check findings.

    Returns:
        A structured ``ReasoningRequest`` ready for provider consumption.
    """
    request = ReasoningRequest()

    # -- Changed files summary --
    request.changed_files_summary = _build_file_summaries(ctx, bundle)

    # -- Plan context --
    if plan is not None:
        request.plan_focus_areas = list(plan.focus_areas)
        request.plan_flags = list(plan.review_flags)
        request.plan_guidance = list(plan.reviewer_guidance)

    # -- Baseline context --
    if ctx.has_baseline and ctx.baseline_profile is not None:
        request.baseline_frameworks = list(ctx.baseline_profile.frameworks)
        request.baseline_auth_patterns = list(ctx.baseline_profile.auth_patterns)

    # -- Memory context --
    if ctx.has_memory and ctx.memory is not None:
        request.memory_categories = list(ctx.memory.categories())
        request.memory_entries = [
            {"category": e.category, "summary": e.summary}
            for e in ctx.memory.entries[:10]
        ]

    # -- Existing concerns --
    if concerns:
        request.existing_concerns = [
            {
                "category": c.category,
                "title": c.title,
                "summary": c.summary,
            }
            for c in concerns
        ]

    # -- Existing observations --
    if observations:
        request.existing_observations = [
            {
                "path": o.path,
                "title": o.title,
                "summary": o.summary,
            }
            for o in observations
        ]

    # -- Deterministic findings --
    if deterministic_findings:
        request.deterministic_findings_summary = [
            {
                "category": f.category.value,
                "title": f.title,
                "file": f.file,
            }
            for f in deterministic_findings
        ]

    return request


def _build_file_summaries(
    ctx: PullRequestContext,
    bundle: ReviewBundle | None,
) -> list[dict[str, str]]:
    """Build per-file summaries from bundle items or raw file list.

    When a bundle is available, each summary includes the review reason
    and focus areas from the bundle item.  Without a bundle, summaries
    are derived from the raw changed file list.
    """
    if bundle is not None and bundle.items:
        return [
            {
                "path": item.path,
                "review_reason": item.review_reason,
                "focus_areas": ", ".join(item.focus_areas) if item.focus_areas else "",
            }
            for item in bundle.items
        ]

    # Fallback: derive from raw PR content
    return [
        {
            "path": f.path,
            "review_reason": "changed_file",
            "focus_areas": "",
        }
        for f in ctx.pr_content.files
    ]
