"""Review observation generator for parity-zero.

Produces per-file ``ReviewObservation`` instances from ``ReviewBundle`` items.
Each observation explains why a specific changed file deserves closer scrutiny,
connecting the file's review reason, focus areas, baseline context, memory
context, and related paths into a targeted, reviewer-like note.

Observation generation rules (Phase 1, heuristic-based):

  - **Auth bundle item in repo with auth patterns** → observation about
    preserving auth flow consistency.
  - **Sensitive+auth combined item** → observation about security boundary
    preservation.
  - **Sensitive config item in framework repo** → observation about
    framework-specific secure defaults.
  - **Item with memory context alignment** → observation that similar areas
    have previously needed scrutiny.
  - **Plain changed file with no meaningful signals** → no observation
    (noise control).

Observations are **not findings**.  They do not claim vulnerabilities,
affect scoring, or appear in the JSON contract.  They are internal
and markdown-visible only.

See ADR-024 for the decision record.
"""

from __future__ import annotations

from reviewer.models import (
    ReviewBundle,
    ReviewBundleItem,
    ReviewObservation,
)

# Maximum number of observations to generate per bundle.
_MAX_OBSERVATIONS = 10

# Maximum number of related paths shown per observation.
_MAX_RELATED_PATHS = 3


def generate_observations(bundle: ReviewBundle) -> list[ReviewObservation]:
    """Generate per-file review observations from a ReviewBundle.

    Iterates over bundle items and produces observations for items that
    carry enough contextual signal to warrant reviewer attention.  Items
    with weak or absent context produce no observations.

    Args:
        bundle: The structured ReviewBundle.

    Returns:
        A list of ReviewObservation instances, possibly empty.
    """
    if not bundle.items:
        return []

    observations: list[ReviewObservation] = []

    for item in bundle.items:
        obs = _observe_item(item, bundle)
        if obs is not None:
            observations.append(obs)
            if len(observations) >= _MAX_OBSERVATIONS:
                break

    return observations


def _observe_item(
    item: ReviewBundleItem,
    bundle: ReviewBundle,
) -> ReviewObservation | None:
    """Attempt to produce an observation for a single bundle item.

    Returns None if the item does not carry enough signal to warrant
    an observation.
    """
    # -- Sensitive + auth combined: boundary preservation --
    if item.review_reason == "sensitive_auth":
        return _sensitive_auth_observation(item, bundle)

    # -- Auth area with baseline auth patterns: consistency --
    if item.review_reason == "auth_area" and bundle.repo_auth_patterns:
        return _auth_consistency_observation(item, bundle)

    # -- Auth area without baseline auth patterns --
    if item.review_reason == "auth_area":
        return _auth_area_observation(item)

    # -- Sensitive path with framework context: framework defaults --
    if item.review_reason == "sensitive_path" and bundle.repo_frameworks:
        return _framework_sensitive_observation(item, bundle)

    # -- Sensitive path without framework context --
    if item.review_reason == "sensitive_path" and not bundle.repo_frameworks:
        return _sensitive_path_observation(item)

    # -- Memory context alignment for any item --
    if item.memory_context:
        return _memory_alignment_observation(item)

    # -- Plain changed file with no meaningful signals → no observation --
    return None


# ======================================================================
# Observation constructors
# ======================================================================


def _sensitive_auth_observation(
    item: ReviewBundleItem,
    bundle: ReviewBundle,
) -> ReviewObservation:
    """Observation for a file that is both sensitive and auth-related."""
    focus = _primary_focus(item, "authentication")
    patterns_note = ""
    if bundle.repo_auth_patterns:
        patterns = ", ".join(bundle.repo_auth_patterns[:3])
        patterns_note = f" Repository auth patterns include {patterns}."

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title="Security boundary in auth-sensitive area",
        summary=(
            f"`{item.path}` sits at an intersection of authentication logic "
            f"and sensitive configuration. Changes here may affect access control "
            f"boundaries or security-critical defaults.{patterns_note}"
        ),
        confidence="medium",
        basis="sensitive_auth_bundle_item",
        related_paths=item.related_paths[:_MAX_RELATED_PATHS],
    )


def _auth_consistency_observation(
    item: ReviewBundleItem,
    bundle: ReviewBundle,
) -> ReviewObservation:
    """Observation for an auth-area file when baseline auth patterns exist."""
    patterns = ", ".join(bundle.repo_auth_patterns[:3])
    focus = _primary_focus(item, "authentication")

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title="Auth flow consistency check warranted",
        summary=(
            f"`{item.path}` modifies authentication-related code in a "
            f"repository using {patterns}. Verify that changes preserve "
            f"existing auth flow integrity and session handling."
        ),
        confidence="medium",
        basis="auth_bundle_item+baseline_patterns",
        related_paths=item.related_paths[:_MAX_RELATED_PATHS],
    )


def _auth_area_observation(item: ReviewBundleItem) -> ReviewObservation:
    """Observation for an auth-area file without baseline patterns."""
    focus = _primary_focus(item, "authentication")

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title="Auth-related path modified",
        summary=(
            f"`{item.path}` appears to be in an authentication or "
            f"authorization-related area. Review access control logic "
            f"for correctness."
        ),
        confidence="low",
        basis="auth_bundle_item",
        related_paths=item.related_paths[:_MAX_RELATED_PATHS],
    )


def _framework_sensitive_observation(
    item: ReviewBundleItem,
    bundle: ReviewBundle,
) -> ReviewObservation:
    """Observation for a sensitive path in a framework-using repo."""
    frameworks = ", ".join(bundle.repo_frameworks[:3])
    focus = _primary_focus(item, "insecure_configuration")

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title="Framework-specific secure defaults",
        summary=(
            f"`{item.path}` is a sensitive configuration path in a "
            f"repository using {frameworks}. Check that framework-specific "
            f"security defaults and conventions are preserved."
        ),
        confidence="low",
        basis="sensitive_bundle_item+framework_context",
        related_paths=item.related_paths[:_MAX_RELATED_PATHS],
    )


def _sensitive_path_observation(item: ReviewBundleItem) -> ReviewObservation:
    """Observation for a sensitive path without framework context."""
    focus = _primary_focus(item, "insecure_configuration")

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title="Sensitive path modified",
        summary=(
            f"`{item.path}` is identified as a sensitive path "
            f"(configuration, deployment, or security-related). "
            f"Review for unintended exposure or weakened controls."
        ),
        confidence="low",
        basis="sensitive_bundle_item",
        related_paths=item.related_paths[:_MAX_RELATED_PATHS],
    )


def _memory_alignment_observation(item: ReviewBundleItem) -> ReviewObservation:
    """Observation for a file with matching memory context."""
    memory_summary = item.memory_context[0] if item.memory_context else ""
    focus = _primary_focus(item, "")

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title="Recurring review attention area",
        summary=(
            f"`{item.path}` aligns with prior review history. "
            f"Similar areas have previously warranted scrutiny"
            f"{': ' + memory_summary if memory_summary else ''}."
        ),
        confidence="low",
        basis="memory_alignment",
        related_paths=item.related_paths[:_MAX_RELATED_PATHS],
    )


# ======================================================================
# Helpers
# ======================================================================


def _primary_focus(item: ReviewBundleItem, default: str) -> str:
    """Return the primary focus area for an item, or a default."""
    return item.focus_areas[0] if item.focus_areas else default
