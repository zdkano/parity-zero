"""Contextual review planner for parity-zero.

Derives a structured ``ReviewPlan`` from ``PullRequestContext`` by
analysing:
  - changed file path overlap with sensitive areas
  - changed file path overlap with auth-related areas
  - baseline auth patterns and framework context
  - relevant historical review memory

The plan **guides review attention** — it does not claim vulnerabilities
or produce findings.  It bridges raw context and the contextual review
reasoning layer, replacing ad-hoc overlap checks with a single, testable
planning step.

See ADR-021 for the decision to introduce this layer.
"""

from __future__ import annotations

from reviewer.models import (
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewPlan,
)


# -- Sensitive path segment list (mirrors baseline.py for overlap detection) --
_SENSITIVE_PATH_SEGMENTS: list[str] = [
    "auth",
    "admin",
    "security",
    "secrets",
    "credentials",
    "keys",
    "certificates",
    "certs",
    "config",
    "settings",
    "deploy",
    "migration",
    "migrations",
    "middleware",
]

# -- Auth-related path segments for direct path matching --
_AUTH_PATH_SEGMENTS: list[str] = [
    "auth",
    "login",
    "oauth",
    "session",
    "token",
    "permissions",
    "rbac",
    "acl",
]


def build_review_plan(ctx: PullRequestContext) -> ReviewPlan:
    """Build a structured review plan from pull request context.

    Analyses the PR delta against baseline profile and review memory
    to determine focus areas, review flags, and guidance for the
    contextual reasoning stage.

    The plan is lightweight and heuristic-based in Phase 1.  It does
    not claim certainty — it shapes review attention.

    Args:
        ctx: The canonical PullRequestContext.

    Returns:
        A ReviewPlan capturing review focus and guidance.
    """
    changed_paths = ctx.pr_content.paths
    plan = ReviewPlan()

    if not changed_paths:
        plan.reviewer_guidance.append("No changed files; review plan is empty.")
        return plan

    # -- Path-based focus --
    _apply_path_focus(plan, changed_paths, ctx.baseline_profile)

    # -- Baseline context --
    if ctx.baseline_profile is not None:
        _apply_baseline_context(plan, ctx.baseline_profile)

    # -- Memory context --
    if ctx.memory is not None:
        _apply_memory_context(plan, changed_paths, ctx.memory)

    # -- Guidance summary --
    _generate_guidance(plan)

    return plan


# ======================================================================
# Path-based focus derivation
# ======================================================================


def _apply_path_focus(
    plan: ReviewPlan,
    changed_paths: list[str],
    baseline_profile: RepoSecurityProfile | None,
) -> None:
    """Derive review focus from changed file paths."""
    baseline_sensitive = (
        baseline_profile.sensitive_paths if baseline_profile else []
    )

    # Sensitive path overlap
    sensitive = sensitive_path_overlap(changed_paths, baseline_sensitive)
    if sensitive:
        plan.sensitive_paths_touched = sensitive
        plan.review_flags.append("touches_sensitive_path")
        # Infer focus areas from sensitive path types
        _add_path_focus_areas(plan, sensitive)

    # Auth path overlap
    auth = auth_path_overlap(changed_paths)
    if auth:
        plan.auth_paths_touched = auth
        plan.review_flags.append("touches_auth_area")
        if "authentication" not in plan.focus_areas:
            plan.focus_areas.append("authentication")
        if "authorization" not in plan.focus_areas:
            plan.focus_areas.append("authorization")


def _add_path_focus_areas(plan: ReviewPlan, paths: list[str]) -> None:
    """Add focus areas inferred from sensitive paths."""
    for path in paths:
        segments = path.lower().split("/")
        if any(seg in ("config", "settings", "deploy") for seg in segments):
            if "insecure_configuration" not in plan.focus_areas:
                plan.focus_areas.append("insecure_configuration")
        if any(seg in ("secrets", "credentials", "keys", "certs",
                        "certificates") for seg in segments):
            if "secrets" not in plan.focus_areas:
                plan.focus_areas.append("secrets")
        if any(seg in ("auth", "login", "oauth", "session", "token",
                        "permissions", "rbac", "acl") for seg in segments):
            if "authentication" not in plan.focus_areas:
                plan.focus_areas.append("authentication")
            if "authorization" not in plan.focus_areas:
                plan.focus_areas.append("authorization")
        if "admin" in segments:
            if "authorization" not in plan.focus_areas:
                plan.focus_areas.append("authorization")
        if any(seg in ("middleware", "security") for seg in segments):
            if "authentication" not in plan.focus_areas:
                plan.focus_areas.append("authentication")


# ======================================================================
# Baseline context application
# ======================================================================


def _apply_baseline_context(
    plan: ReviewPlan,
    profile: RepoSecurityProfile,
) -> None:
    """Apply baseline repository context to the review plan."""
    if profile.auth_patterns:
        plan.auth_pattern_context = list(profile.auth_patterns[:4])
        if "touches_auth_area" not in plan.review_flags and plan.auth_paths_touched:
            plan.review_flags.append("touches_auth_area")

    if profile.frameworks:
        plan.framework_context = list(profile.frameworks[:4])


# ======================================================================
# Memory context application
# ======================================================================


def _apply_memory_context(
    plan: ReviewPlan,
    changed_paths: list[str],
    memory: ReviewMemory,
) -> None:
    """Apply review memory context to the review plan."""
    if not memory.entries:
        return

    path_categories = infer_path_categories(changed_paths)
    memory_categories = set(memory.categories())

    relevant = sorted(path_categories & memory_categories)
    if relevant:
        plan.relevant_memory_categories = relevant
        plan.review_flags.append("has_relevant_memory")
        # Memory categories can add focus areas
        for cat in relevant:
            if cat not in plan.focus_areas:
                plan.focus_areas.append(cat)


# ======================================================================
# Guidance generation
# ======================================================================


def _generate_guidance(plan: ReviewPlan) -> None:
    """Generate reviewer guidance notes from the plan state."""
    if plan.sensitive_paths_touched:
        count = len(plan.sensitive_paths_touched)
        plan.reviewer_guidance.append(
            f"PR touches {count} sensitive path(s); "
            f"warrant closer security review."
        )

    if plan.auth_paths_touched:
        plan.reviewer_guidance.append(
            "PR modifies auth-related path(s); "
            "verify access control logic remains correct."
        )

    if plan.auth_pattern_context:
        patterns = ", ".join(plan.auth_pattern_context)
        plan.reviewer_guidance.append(
            f"Repository uses auth patterns: {patterns}. "
            f"Review changes for consistency."
        )

    if plan.framework_context:
        frameworks = ", ".join(plan.framework_context)
        plan.reviewer_guidance.append(
            f"Repository uses: {frameworks}. "
            f"Consider framework-specific security conventions."
        )

    if plan.relevant_memory_categories:
        cats = ", ".join(plan.relevant_memory_categories)
        plan.reviewer_guidance.append(
            f"Historical review memory covers: {cats}. "
            f"Prior concerns in these areas are noted."
        )


# ======================================================================
# Path analysis helpers (canonical location — also re-exported by
# reasoning.py for backward compatibility)
# ======================================================================


def sensitive_path_overlap(
    changed_paths: list[str],
    baseline_sensitive: list[str],
) -> list[str]:
    """Return changed paths that overlap with baseline sensitive paths.

    A changed path overlaps if it exactly matches a baseline sensitive path
    or if any of its path segments match known sensitive path segments.
    """
    baseline_set = set(baseline_sensitive)
    overlapping: list[str] = []

    for path in changed_paths:
        # Direct match with baseline sensitive paths
        if path in baseline_set:
            overlapping.append(path)
            continue
        # Segment-based match
        segments = path.lower().split("/")
        if any(seg in _SENSITIVE_PATH_SEGMENTS for seg in segments):
            overlapping.append(path)

    return overlapping


def auth_path_overlap(changed_paths: list[str]) -> list[str]:
    """Return changed paths that appear to be in auth-related areas."""
    auth_paths: list[str] = []
    for path in changed_paths:
        segments = path.lower().split("/")
        if any(seg in _AUTH_PATH_SEGMENTS for seg in segments):
            auth_paths.append(path)
    return auth_paths


def infer_path_categories(changed_paths: list[str]) -> set[str]:
    """Infer likely finding categories from changed file paths.

    This is a lightweight heuristic — it maps path segments to
    the finding taxonomy categories to enable memory relevance matching.
    """
    categories: set[str] = set()
    for path in changed_paths:
        path_lower = path.lower()
        segments = path_lower.split("/")

        # Auth-related paths
        if any(seg in ("auth", "login", "oauth", "session", "token",
                        "permissions", "rbac", "acl") for seg in segments):
            categories.add("authentication")
            categories.add("authorization")

        # Config/settings paths
        if any(seg in ("config", "settings", "deploy") for seg in segments):
            categories.add("insecure_configuration")
            categories.add("secrets")

        # Security paths
        if any(seg in ("security", "middleware") for seg in segments):
            categories.add("authentication")
            categories.add("authorization")

        # Admin paths
        if "admin" in segments:
            categories.add("authorization")

        # Dependency files
        basename = path.split("/")[-1].lower() if "/" in path else path_lower
        if basename in ("requirements.txt", "package.json", "go.mod",
                        "cargo.toml", "gemfile", "pom.xml", "build.gradle",
                        "composer.json"):
            categories.add("dependency_risk")

    return categories


def relevant_memory_entries(
    changed_paths: list[str],
    memory: ReviewMemory,
) -> list:
    """Return memory entries relevant to the current PR paths.

    An entry is relevant if its category matches a category inferred
    from the changed file paths.
    """
    path_categories = infer_path_categories(changed_paths)
    if not path_categories:
        return []

    return [
        entry for entry in memory.entries
        if entry.category in path_categories
    ]
