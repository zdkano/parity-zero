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
- **bounded code evidence** for the most relevant review targets (ADR-043)

This is a **first-class part of the reviewer pipeline** — it bridges the
reviewer's structured context and the reasoning provider interface.

Phase 1: focuses on structure and clarity.  Prompt wording optimisation
is deferred to later iterations when provider integration is live.

See ADR-025 for the decision record and ADR-043 for code evidence.
"""

from __future__ import annotations

from reviewer.models import (
    PullRequestContext,
    ReviewBundle,
    ReviewBundleItem,
    ReviewConcern,
    ReviewObservation,
    ReviewPlan,
)
from reviewer.providers import ReasoningRequest
from schemas.findings import Finding

# Maximum number of review targets with code evidence sent to the provider.
_MAX_REVIEW_TARGETS = 8

# Maximum character length for a code excerpt per review target.
_MAX_EXCERPT_CHARS = 1500

# Review reason priority order — higher-priority items are selected first.
_REASON_PRIORITY: dict[str, int] = {
    "sensitive_auth": 0,
    "api_surface": 1,
    "auth_area": 2,
    "sensitive_path": 3,
    "changed_file": 4,
}


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

    # -- Bounded code evidence from ReviewBundle (ADR-043) --
    request.review_targets = _build_review_targets(bundle)

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


def _build_review_targets(bundle: ReviewBundle | None) -> list[dict[str, str]]:
    """Build bounded, prioritized review targets with code evidence.

    Selects the most security-relevant bundle items and includes
    bounded code excerpts for each.  This gives the provider actual
    code to reason about instead of just file path metadata.

    Prioritization:
      1. sensitive_auth — files in both sensitive and auth areas
      2. api_surface — new routes, endpoints, controllers
      3. auth_area — authentication/authorization code
      4. sensitive_path — other sensitive areas
      5. changed_file — remaining changes (included only to fill quota)

    Returns an empty list when no bundle is available.
    """
    if bundle is None or not bundle.items:
        return []

    # Sort items by review reason priority (most relevant first).
    prioritized = sorted(
        bundle.items,
        key=lambda item: _REASON_PRIORITY.get(item.review_reason, 99),
    )

    targets: list[dict[str, str]] = []
    for item in prioritized[:_MAX_REVIEW_TARGETS]:
        target = _bundle_item_to_target(item)
        targets.append(target)

    return targets


def _bundle_item_to_target(item: ReviewBundleItem) -> dict[str, str]:
    """Convert a single ReviewBundleItem into a review target dict."""
    target: dict[str, str] = {
        "path": item.path,
        "reason": item.review_reason,
        "focus_areas": ", ".join(item.focus_areas) if item.focus_areas else "",
        "code_excerpt": _bounded_excerpt(item.content),
    }

    if item.related_paths:
        target["related_paths"] = ", ".join(item.related_paths)

    if item.memory_context:
        target["memory_context"] = "; ".join(item.memory_context)

    if item.baseline_context:
        target["baseline_context"] = "; ".join(item.baseline_context)

    return target


def _bounded_excerpt(content: str) -> str:
    """Return a bounded code excerpt from file content.

    Truncates to ``_MAX_EXCERPT_CHARS`` characters.  If truncated,
    appends a marker so the provider knows the content was cut.
    Returns empty string for empty/None content.
    """
    if not content:
        return ""
    if len(content) <= _MAX_EXCERPT_CHARS:
        return content
    return content[:_MAX_EXCERPT_CHARS] + "\n... [truncated]"
