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

Provider-backed observation refinement (ADR-028):

  When provider ``CandidateNote`` output is available, observations may be
  enriched or supplemented:

  - **Enrichment** — a provider note that targets the same file as an
    existing observation may add concise detail to that observation's summary.
  - **Supplementary observations** — a provider note that targets a specific
    file not already covered by an observation may generate a new observation
    with basis ``provider_refinement``.

  Provider-backed observations remain non-finding, non-scoring, and use
  hedged language (``may``, ``worth verifying``).

Observations are **not findings**.  They do not claim vulnerabilities,
affect scoring, or appear in the JSON contract.  They are internal
and markdown-visible only.

See ADR-024 for the initial decision record and ADR-028 for the
provider-backed refinement decision.
"""

from __future__ import annotations

from reviewer.models import (
    ReviewBundle,
    ReviewBundleItem,
    ReviewObservation,
)
from reviewer.providers import CandidateNote

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
    basename = _file_basename(item.path)
    patterns_note = ""
    if bundle.repo_auth_patterns:
        patterns = ", ".join(bundle.repo_auth_patterns[:3])
        patterns_note = f" Repository auth patterns include {patterns}."

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title=f"Auth-sensitive boundary: {basename}",
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
    basename = _file_basename(item.path)

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title=f"Auth flow consistency: {basename}",
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
    basename = _file_basename(item.path)

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title=f"Auth-related change: {basename}",
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
    basename = _file_basename(item.path)

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title=f"Framework defaults: {basename} ({frameworks})",
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
    basename = _file_basename(item.path)

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title=f"Sensitive path change: {basename}",
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
    basename = _file_basename(item.path)

    return ReviewObservation(
        path=item.path,
        focus_area=focus,
        title=f"Recurring review area: {basename}",
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
# Provider-backed observation refinement (ADR-028)
# ======================================================================

# Maximum characters of provider detail appended during enrichment.
_MAX_ENRICHMENT_CHARS = 200

# Minimum characters of provider detail required for enrichment.
# Notes shorter than this are too terse to add meaningful context.
_MIN_ENRICHMENT_CHARS = 30

# Maximum supplementary observations from provider notes.
_MAX_SUPPLEMENTARY = 3

# Minimum summary length for a provider note to qualify as supplementary.
_MIN_SUPPLEMENTARY_SUMMARY_LENGTH = 15

# Keyword overlap threshold for matching a note to an observation.
# 35% is intentionally lower than the 60% suppression threshold in
# reasoning.py — enrichment requires less overlap than suppression
# because adding detail is lower risk than discarding content.
# This is a tunable heuristic (see ADR-028 deferred concerns).
_MATCH_KEYWORD_THRESHOLD = 0.35

# Stopwords excluded from keyword extraction (shared with reasoning.py).
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that", "these",
    "those", "it", "its", "of", "in", "to", "for", "with", "on", "at",
    "by", "from", "as", "or", "and", "but", "not", "no", "if", "so",
    "than", "too", "very", "just", "about", "into", "over", "after",
})


def refine_observations(
    observations: list[ReviewObservation],
    provider_notes: list[CandidateNote],
) -> list[ReviewObservation]:
    """Refine observations using provider-backed candidate notes (ADR-028).

    Provider notes may enrich existing observations or generate
    supplementary observations for files not already covered.

    Trust boundaries:
    - Observations remain non-finding and non-scoring.
    - Enrichment appends hedged provider detail; it does not replace
      the original observation text.
    - Supplementary observations use ``basis="provider_refinement"``
      and hedged language.
    - Total observations are capped at ``_MAX_OBSERVATIONS``.

    Args:
        observations: Existing deterministic observations.
        provider_notes: Normalized candidate notes from the provider,
            already after overlap suppression.

    Returns:
        A refined list of ReviewObservation instances.
    """
    if not provider_notes:
        return observations

    # Build a lookup of observation paths for matching.
    obs_by_path: dict[str, list[int]] = {}
    for idx, obs in enumerate(observations):
        if obs.path:
            obs_by_path.setdefault(obs.path, []).append(idx)

    # Track which notes are consumed by enrichment.
    used_note_indices: set[int] = set()

    # Work on a copy to avoid mutating originals.
    refined = [
        ReviewObservation(
            path=o.path,
            focus_area=o.focus_area,
            title=o.title,
            summary=o.summary,
            confidence=o.confidence,
            basis=o.basis,
            related_paths=list(o.related_paths),
        )
        for o in observations
    ]

    # -- Phase 1: Enrich existing observations with matching notes --
    # Track enriched observation indices to avoid double-enrichment.
    enriched_obs_indices: set[int] = set()
    for note_idx, note in enumerate(provider_notes):
        if not note.summary:
            continue
        match_idx = _find_matching_observation(note, refined, obs_by_path)
        if match_idx is not None and match_idx not in enriched_obs_indices:
            _enrich_observation(refined[match_idx], note)
            used_note_indices.add(note_idx)
            enriched_obs_indices.add(match_idx)

    # -- Phase 2: Create supplementary observations from unmatched notes --
    covered_paths = {o.path for o in refined if o.path}
    supplementary_count = 0

    for note_idx, note in enumerate(provider_notes):
        if note_idx in used_note_indices:
            continue
        if supplementary_count >= _MAX_SUPPLEMENTARY:
            break
        if len(refined) >= _MAX_OBSERVATIONS:
            break
        # Only create supplementary for notes targeting specific files.
        target_paths = [p for p in note.related_paths if p and p not in covered_paths]
        if not target_paths:
            continue
        if not note.summary or len(note.summary.strip()) < _MIN_SUPPLEMENTARY_SUMMARY_LENGTH:
            continue
        obs = _supplementary_observation(note, target_paths[0])
        refined.append(obs)
        covered_paths.add(obs.path)
        supplementary_count += 1

    return refined[:_MAX_OBSERVATIONS]


def _find_matching_observation(
    note: CandidateNote,
    observations: list[ReviewObservation],
    obs_by_path: dict[str, list[int]],
) -> int | None:
    """Find the best matching observation for a provider note.

    Matches by path overlap first, then by keyword similarity.
    Returns the index of the best match, or None.
    """
    # Try path-based match first.
    for path in note.related_paths:
        if path in obs_by_path:
            return obs_by_path[path][0]

    # Fall back to keyword similarity.
    note_keywords = _extract_keywords(note.title) | _extract_keywords(note.summary)
    if not note_keywords:
        return None

    best_idx: int | None = None
    best_ratio = 0.0

    for idx, obs in enumerate(observations):
        obs_keywords = _extract_keywords(obs.title) | _extract_keywords(obs.summary)
        if not obs_keywords:
            continue
        overlap = note_keywords & obs_keywords
        ratio = len(overlap) / len(note_keywords)
        if ratio > best_ratio and ratio >= _MATCH_KEYWORD_THRESHOLD:
            best_ratio = ratio
            best_idx = idx

    return best_idx


def _enrich_observation(obs: ReviewObservation, note: CandidateNote) -> None:
    """Enrich an observation's summary with provider note detail.

    Appends a hedged, capped addendum to the existing summary.
    Does not replace the original text.  Marks the basis as enriched.

    Skips enrichment when the provider detail is too short or too
    generic to add meaningful file-specific insight.
    """
    detail = note.summary.strip()
    # Skip enrichment when detail is too short to be useful.
    if len(detail) < _MIN_ENRICHMENT_CHARS:
        return
    # Skip when detail heavily overlaps with existing summary.
    obs_kw = _extract_keywords(obs.summary)
    note_kw = _extract_keywords(detail)
    if note_kw and obs_kw:
        overlap = note_kw & obs_kw
        ratio = len(overlap) / len(note_kw) if note_kw else 0
        if ratio > 0.6:
            return
    if len(detail) > _MAX_ENRICHMENT_CHARS:
        detail = detail[:_MAX_ENRICHMENT_CHARS].rsplit(" ", 1)[0] + "…"

    obs.summary = (
        f"{obs.summary} Additionally, provider analysis suggests: {detail}"
    )
    if "provider_enriched" not in obs.basis:
        obs.basis = f"{obs.basis}+provider_enriched"


def _supplementary_observation(
    note: CandidateNote,
    target_path: str,
) -> ReviewObservation:
    """Create a supplementary observation from an unmatched provider note.

    Uses hedged language and clearly marks the basis as provider-derived.
    """
    summary = note.summary.strip()
    if len(summary) > _MAX_ENRICHMENT_CHARS:
        summary = summary[:_MAX_ENRICHMENT_CHARS].rsplit(" ", 1)[0] + "…"

    title = note.title.strip() if note.title else "Provider-noted area of interest"
    confidence = note.confidence if note.confidence in ("low", "medium") else "low"

    return ReviewObservation(
        path=target_path,
        focus_area="",
        title=title,
        summary=(
            f"`{target_path}` may warrant attention: {summary}"
        ),
        confidence=confidence,
        basis="provider_refinement",
        related_paths=[p for p in note.related_paths if p != target_path][:_MAX_RELATED_PATHS],
    )


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful lowercase keywords from text."""
    if not text:
        return set()
    words = set(text.lower().split())
    return {w.strip(".,;:!?\"'`()[]{}") for w in words if len(w) > 2} - _STOPWORDS


# ======================================================================
# Helpers
# ======================================================================


def _primary_focus(item: ReviewBundleItem, default: str) -> str:
    """Return the primary focus area for an item, or a default."""
    return item.focus_areas[0] if item.focus_areas else default


def _file_basename(path: str) -> str:
    """Extract a short file basename from a full path for use in titles."""
    if not path:
        return "unknown"
    parts = path.rsplit("/", 1)
    return parts[-1] if parts else path
