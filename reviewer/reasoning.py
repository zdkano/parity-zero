"""Contextual security review layer for parity-zero.

This module provides the **primary review path** — contextual, reasoning-based
security analysis that consumes:

  - PR delta (changed files and their content)
  - baseline repository security profile (ADR-015)
  - review memory and prior findings themes (ADR-016)
  - deterministic support signals (ADR-013, consumed via engine)
  - policy/intent context (later phases)

It produces contextual findings and reviewer notes that form the core of
parity-zero's security review value.

This is **not** a thin wrapper over deterministic checks.  The intended role
is to reason about security implications like a security engineer who
understands the repository context — see ADR-014.

See also: architecture.md § Reasoning Layer (Contextual Review).

Phase 1 implementation: baseline-aware and memory-aware contextual review
notes.  The layer uses ``PullRequestContext`` as its canonical input and
produces structured notes based on overlap between PR delta, repo baseline,
and review memory.  LLM integration will be added in a subsequent iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.findings import Finding
from reviewer.models import PullRequestContext, RepoSecurityProfile, ReviewMemory


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
    """

    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_reasoning(ctx: PullRequestContext | dict[str, str]) -> ReasoningResult:
    """Run contextual security review against changed files with repo context.

    ``PullRequestContext`` is the **canonical input** (ADR-018, ADR-019).
    A raw ``dict[str, str]`` is accepted for backward compatibility but
    is automatically wrapped — callers should migrate to
    ``PullRequestContext``.

    Phase 1 behaviour:
    - produces contextual notes based on baseline profile overlap
    - surfaces relevant review memory as historical awareness
    - does not yet produce LLM-generated findings
    - notes are informational and do not affect decision or risk_score

    Args:
        ctx: A ``PullRequestContext`` (preferred) or a legacy
            ``{path: content}`` dict.

    Returns:
        A ReasoningResult with contextual notes and (currently empty)
        findings.
    """
    # -- Normalise input --
    if isinstance(ctx, dict):
        ctx = PullRequestContext.from_dict(ctx)

    file_contents = ctx.pr_content.to_dict()
    changed_paths = ctx.pr_content.paths
    notes: list[str] = []

    if not file_contents:
        notes.append("No changed files provided for contextual review.")
        return ReasoningResult(findings=[], notes=notes)

    file_count = len(file_contents)
    notes.append(
        f"Contextual review examined {file_count} file(s)."
    )

    # -- Baseline-aware contextual notes --
    if ctx.has_baseline and ctx.baseline_profile is not None:
        _add_baseline_notes(notes, changed_paths, ctx.baseline_profile)

    # -- Memory-aware contextual notes --
    if ctx.has_memory and ctx.memory is not None:
        _add_memory_notes(notes, changed_paths, ctx.memory)

    return ReasoningResult(findings=[], notes=notes)


# ======================================================================
# Baseline-aware contextual review
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


def _sensitive_path_overlap(
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


def _auth_path_overlap(changed_paths: list[str]) -> list[str]:
    """Return changed paths that appear to be in auth-related areas."""
    auth_paths: list[str] = []
    for path in changed_paths:
        segments = path.lower().split("/")
        if any(seg in _AUTH_PATH_SEGMENTS for seg in segments):
            auth_paths.append(path)
    return auth_paths


# ======================================================================
# Memory-aware contextual review
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


def _infer_path_categories(changed_paths: list[str]) -> set[str]:
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


def _relevant_memory_entries(
    changed_paths: list[str],
    memory: ReviewMemory,
) -> list:
    """Return memory entries relevant to the current PR paths.

    An entry is relevant if its category matches a category inferred
    from the changed file paths.
    """
    path_categories = _infer_path_categories(changed_paths)
    if not path_categories:
        return []

    return [
        entry for entry in memory.entries
        if entry.category in path_categories
    ]
