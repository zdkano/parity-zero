"""Reasoning input assembly for parity-zero (ADR-025, ADR-047).

Builds a structured ``ReasoningRequest`` from the reviewer pipeline context:
- ReviewPlan (focus areas, flags, guidance)
- ReviewBundle (per-file evidence with context)
- Baseline profile (frameworks, auth patterns)
- Review memory (relevant categories and entries)
- Deterministic findings (supporting signals)
- Existing concerns and observations

The assembled request makes explicit:
- what changed (deterministic change summary — ADR-047)
- what deserves scrutiny
- what baseline context matters
- what memory context matters
- what observations/concerns already exist
- **bounded code evidence** for the most relevant review targets (ADR-043)
- **fuller bounded changed-file context** for review units (ADR-047)

This is a **first-class part of the reviewer pipeline** — it bridges the
reviewer's structured context and the reasoning provider interface.

Phase 1: focuses on structure and clarity.  Prompt wording optimisation
is deferred to later iterations when provider integration is live.

See ADR-025 for the decision record, ADR-043 for code evidence,
and ADR-047 for fuller changed-file context and change summary.
"""

from __future__ import annotations

from reviewer.change_summary import build_change_summary
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
# ADR-046: Increased from 1500 to 2500 to provide more complete bounded
# review units (complete functions/handlers) rather than tiny snippets.
_MAX_EXCERPT_CHARS = 2500

# Maximum total characters for all related code excerpts combined.
_MAX_RELATED_CHARS = 1200

# Maximum character length for a compact related-context excerpt.
_MAX_COMPACT_EXCERPT_CHARS = 400

# ADR-047: Threshold for including full file content instead of excerpts.
# Files smaller than this are included in full for better review context.
_FULL_FILE_THRESHOLD = 3000

# ADR-047: Maximum chars for a diff-context annotation per file.
_MAX_DIFF_ANNOTATION_CHARS = 500

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

    # -- Deterministic change summary (ADR-047) --
    request.change_summary = build_change_summary(bundle, plan)

    # -- Changed files summary --
    request.changed_files_summary = _build_file_summaries(ctx, bundle)

    # -- Bounded code evidence from ReviewBundle (ADR-043, ADR-047) --
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

    ADR-046: Prefers complete bounded review units over tiny snippets.
    ADR-047: Includes fuller bounded changed-file context — full file
    content for small relevant files and file-level change annotations.

    For security-relevant items (sensitive_auth, api_surface, auth_area),
    includes related context from the same review unit when available.

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

    # Build a lookup of all bundle items by path for related-context inclusion.
    items_by_path: dict[str, ReviewBundleItem] = {
        item.path: item for item in bundle.items
    }

    targets: list[dict[str, str]] = []
    included_paths: set[str] = set()

    for item in prioritized:
        if len(targets) >= _MAX_REVIEW_TARGETS:
            break
        if item.path in included_paths:
            continue

        target = _bundle_item_to_target(item)

        # ADR-046: For high-priority items, include compact related-context
        # excerpts to form more complete review units.
        if item.review_reason in ("sensitive_auth", "api_surface", "auth_area"):
            related_excerpts = _gather_related_excerpts(
                item, items_by_path, included_paths,
            )
            if related_excerpts:
                target["related_code"] = related_excerpts

        targets.append(target)
        included_paths.add(item.path)

    return targets


def _gather_related_excerpts(
    item: ReviewBundleItem,
    items_by_path: dict[str, ReviewBundleItem],
    already_included: set[str],
) -> str:
    """Gather compact code excerpts from related paths for review context.

    Returns a combined string of related code context, bounded to avoid
    prompt explosion.  Only includes paths that are not already primary
    review targets.

    ADR-046: This gives the provider route+controller or route+validation
    groupings rather than isolated code fragments.
    """
    if not item.related_paths:
        return ""

    excerpts: list[str] = []
    total_chars = 0

    for rel_path in item.related_paths[:3]:
        if rel_path in already_included:
            continue
        rel_item = items_by_path.get(rel_path)
        if not rel_item or not rel_item.content:
            continue
        # Compact excerpt — smaller than primary targets.
        excerpt = _bounded_excerpt_compact(rel_item.content, _MAX_COMPACT_EXCERPT_CHARS)
        if not excerpt:
            continue
        if total_chars + len(excerpt) > _MAX_RELATED_CHARS:
            break
        excerpts.append(f"--- {rel_path} ---\n{excerpt}")
        total_chars += len(excerpt)

    return "\n".join(excerpts)


def _bounded_excerpt_compact(content: str, max_chars: int = 400) -> str:
    """Return a compact bounded excerpt for related context inclusion."""
    if not content:
        return ""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n... [truncated]"


def _bundle_item_to_target(item: ReviewBundleItem) -> dict[str, str]:
    """Convert a single ReviewBundleItem into a review target dict.

    ADR-047: For small/moderate files (under ``_FULL_FILE_THRESHOLD``),
    includes the full file content instead of a truncated excerpt.
    This gives the provider complete bounded review units for routes,
    controllers, validation, and model files.

    Also adds a ``file_context`` annotation describing what kind of file
    this is based on its review reason and focus areas.
    """
    # ADR-047: Prefer full file content for small relevant files.
    is_high_priority = item.review_reason in (
        "sensitive_auth", "api_surface", "auth_area", "sensitive_path",
    )
    content_len = len(item.content) if item.content else 0

    if is_high_priority and 0 < content_len <= _FULL_FILE_THRESHOLD:
        code_excerpt = item.content
    else:
        code_excerpt = _bounded_excerpt(item.content)

    target: dict[str, str] = {
        "path": item.path,
        "reason": item.review_reason,
        "focus_areas": ", ".join(item.focus_areas) if item.focus_areas else "",
        "code_excerpt": code_excerpt,
    }

    # ADR-047: Add file-level context annotation.
    file_ctx = _build_file_context_annotation(item)
    if file_ctx:
        target["file_context"] = file_ctx

    if item.related_paths:
        target["related_paths"] = ", ".join(item.related_paths)

    if item.memory_context:
        target["memory_context"] = "; ".join(item.memory_context)

    if item.baseline_context:
        target["baseline_context"] = "; ".join(item.baseline_context)

    return target


def _build_file_context_annotation(item: ReviewBundleItem) -> str:
    """Build a short annotation describing the file's role and change type.

    ADR-047: This helps the provider understand what the file is and why
    it matters, without requiring the provider to guess from the path alone.
    """
    parts: list[str] = []

    if item.review_reason == "sensitive_auth":
        parts.append("sensitive auth file")
    elif item.review_reason == "api_surface":
        parts.append("API surface file")
    elif item.review_reason == "auth_area":
        parts.append("auth-related file")
    elif item.review_reason == "sensitive_path":
        parts.append("sensitive path")

    if item.focus_areas:
        parts.append(f"focus: {', '.join(item.focus_areas[:3])}")

    if item.content:
        content_len = len(item.content)
        if content_len <= _FULL_FILE_THRESHOLD:
            parts.append("full file included")
        else:
            parts.append(f"excerpt from {content_len} chars")

    annotation = "; ".join(parts)
    return annotation[:_MAX_DIFF_ANNOTATION_CHARS] if annotation else ""


def _bounded_excerpt(content: str) -> str:
    """Return a bounded code excerpt from file content.

    ADR-046: Prefers complete bounded review units (function bodies,
    route handlers) over arbitrary truncation.  When content fits within
    the limit, returns it in full.  When truncation is needed, attempts
    to break at a natural boundary (function/class definition) rather
    than mid-statement.

    Returns empty string for empty/None content.
    """
    if not content:
        return ""
    if len(content) <= _MAX_EXCERPT_CHARS:
        return content

    # Try to find a natural boundary near the limit.
    excerpt = content[:_MAX_EXCERPT_CHARS]
    boundary = _find_natural_boundary(excerpt)
    if boundary > _MAX_EXCERPT_CHARS // 2:
        return content[:boundary] + "\n... [truncated at function boundary]"
    return excerpt + "\n... [truncated]"


def _find_natural_boundary(text: str) -> int:
    """Find the best natural code boundary (function/class def) position.

    Searches backward from the end of text for a line starting with
    a function or class definition, returning the position just before
    that line.  Returns 0 if no boundary is found.
    """
    # Common function/class definition patterns across languages.
    boundary_markers = (
        "\ndef ", "\nclass ", "\nasync def ",
        "\nfunction ", "\nexport function ", "\nexport default function ",
        "\nconst ", "\nlet ",
        "\npub fn ", "\nfn ",
        "\nfunc ",
        "\npublic ", "\nprivate ", "\nprotected ",
        "\nrouter.", "\napp.",
    )
    best = 0
    for marker in boundary_markers:
        pos = text.rfind(marker)
        if pos > best:
            best = pos
    return best
