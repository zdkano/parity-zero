"""Review bundle builder for parity-zero.

Assembles a ``ReviewBundle`` — structured review evidence gathered from
PR delta, baseline profile, review memory, and the review plan.

The bundle sits between ``PullRequestContext`` / ``ReviewPlan`` and the
contextual review / future reasoning layers.  It makes the reviewer
operate on better structured review evidence rather than ad-hoc paths
and notes.

Builder heuristics (Phase 1):
  - files in sensitive areas → tagged with ``sensitive_path`` reason
  - files in auth areas → tagged with ``auth_area`` reason
  - files matching both → tagged with ``sensitive_auth`` reason
  - files matching memory categories → enriched with memory context
  - remaining files → included with ``changed_file`` reason
  - related paths are bounded (max 3 per item)
  - plan guidance is carried as ``plan_summary``
  - baseline frameworks and auth patterns are carried as aggregate context

The builder is intentionally lightweight.  It does not perform AST
analysis, code-graph traversal, or provider-backed reasoning.

See ADR-023 for the decision record.
"""

from __future__ import annotations

from reviewer.models import (
    PullRequestContext,
    ReviewBundle,
    ReviewBundleItem,
    ReviewPlan,
)
from reviewer.planner import (
    auth_path_overlap,
    infer_path_categories,
    relevant_memory_entries,
    sensitive_path_overlap,
)

# Maximum number of related paths per bundle item.
_MAX_RELATED_PATHS = 3

# Maximum number of memory context entries surfaced per item.
_MAX_MEMORY_CONTEXT_PER_ITEM = 3


def build_review_bundle(
    ctx: PullRequestContext,
    plan: ReviewPlan,
) -> ReviewBundle:
    """Build a ReviewBundle from PR context and review plan.

    Gathers review-relevant evidence for each changed file based on
    heuristic matching against the review plan, baseline profile, and
    review memory.

    Args:
        ctx: The canonical PullRequestContext.
        plan: The structured ReviewPlan derived from the same context.

    Returns:
        A ReviewBundle with items for each changed file, annotated
        with review reasons and surrounding context.
    """
    bundle = ReviewBundle(
        plan_summary=list(plan.reviewer_guidance),
        repo_frameworks=list(plan.framework_context),
        repo_auth_patterns=list(plan.auth_pattern_context),
    )

    if not ctx.pr_content.files:
        return bundle

    # -- Pre-compute path sets for efficient lookup --
    changed_paths = ctx.pr_content.paths
    sensitive_set = set(plan.sensitive_paths_touched)
    auth_set = set(plan.auth_paths_touched)

    # -- Pre-compute memory relevance --
    memory_by_path: dict[str, list[str]] = {}
    if ctx.has_memory and ctx.memory is not None:
        for path in changed_paths:
            entries = relevant_memory_entries([path], ctx.memory)
            if entries:
                memory_by_path[path] = [
                    f"{e.category}: {e.summary}"
                    for e in entries[:_MAX_MEMORY_CONTEXT_PER_ITEM]
                ]

    # -- Build items --
    for pr_file in ctx.pr_content.files:
        path = pr_file.path
        is_sensitive = path in sensitive_set
        is_auth = path in auth_set

        # -- Determine review reason --
        review_reason = _classify_review_reason(is_sensitive, is_auth)

        # -- Determine focus areas for this file --
        file_focus = _file_focus_areas(path, plan)

        # -- Determine baseline context --
        baseline_ctx = _file_baseline_context(
            path, is_sensitive, is_auth, plan,
        )

        # -- Determine memory context --
        memory_ctx = memory_by_path.get(path, [])

        # -- Determine related paths --
        related = _related_paths(path, changed_paths, is_sensitive, is_auth, plan)

        bundle.items.append(ReviewBundleItem(
            path=path,
            content=pr_file.content,
            review_reason=review_reason,
            focus_areas=file_focus,
            baseline_context=baseline_ctx,
            memory_context=memory_ctx,
            related_paths=related,
        ))

    return bundle


def _classify_review_reason(is_sensitive: bool, is_auth: bool) -> str:
    """Classify the primary review reason for a file."""
    if is_sensitive and is_auth:
        return "sensitive_auth"
    if is_sensitive:
        return "sensitive_path"
    if is_auth:
        return "auth_area"
    return "changed_file"


def _file_focus_areas(path: str, plan: ReviewPlan) -> list[str]:
    """Determine which plan focus areas apply to this specific file."""
    path_categories = infer_path_categories([path])
    plan_focus_set = set(plan.focus_areas)

    # Focus areas relevant to this file = intersection of
    # file-inferred categories and plan focus areas, plus any
    # plan focus areas if the file is in a sensitive/auth area.
    relevant = sorted(path_categories & plan_focus_set)

    # If the file has no category overlap but is in a sensitive
    # or auth area, carry all plan focus areas as potential context.
    if not relevant and plan_focus_set:
        segments = set(path.lower().split("/"))
        sensitive_segments = {
            "auth", "admin", "security", "secrets", "credentials",
            "keys", "config", "settings", "deploy", "middleware",
        }
        if segments & sensitive_segments:
            relevant = sorted(plan_focus_set)

    return relevant


def _file_baseline_context(
    path: str,
    is_sensitive: bool,
    is_auth: bool,
    plan: ReviewPlan,
) -> list[str]:
    """Derive baseline context notes relevant to a specific file."""
    context: list[str] = []

    if is_auth and plan.auth_pattern_context:
        patterns = ", ".join(plan.auth_pattern_context[:3])
        context.append(f"repo auth patterns: {patterns}")

    if (is_sensitive or is_auth) and plan.framework_context:
        frameworks = ", ".join(plan.framework_context[:3])
        context.append(f"repo frameworks: {frameworks}")

    return context


def _related_paths(
    path: str,
    all_changed_paths: list[str],
    is_sensitive: bool,
    is_auth: bool,
    plan: ReviewPlan,
) -> list[str]:
    """Find other changed paths related to this file.

    Relatedness is determined by:
    - sharing the same directory
    - both being in sensitive or auth areas
    """
    if len(all_changed_paths) <= 1:
        return []

    related: list[str] = []

    # Same directory
    path_dir = "/".join(path.split("/")[:-1]) if "/" in path else ""
    if path_dir:
        for other in all_changed_paths:
            if other == path:
                continue
            other_dir = "/".join(other.split("/")[:-1]) if "/" in other else ""
            if other_dir == path_dir and other not in related:
                related.append(other)

    # Both in sensitive/auth areas
    sensitive_set = set(plan.sensitive_paths_touched)
    auth_set = set(plan.auth_paths_touched)

    if is_sensitive:
        for other in plan.sensitive_paths_touched:
            if other != path and other not in related:
                related.append(other)

    if is_auth:
        for other in plan.auth_paths_touched:
            if other != path and other not in related:
                related.append(other)

    return related[:_MAX_RELATED_PATHS]
