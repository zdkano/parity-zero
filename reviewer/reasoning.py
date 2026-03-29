"""Contextual security review layer for parity-zero.

This module provides the **primary review path** — contextual, reasoning-based
security analysis that consumes:

  - PR delta (changed files and their content)
  - baseline repository security profile (ADR-015)
  - review memory and prior findings themes (ADR-016)
  - structured review plan (ADR-021)
  - deterministic support signals (ADR-013, consumed via engine)
  - provider-backed reasoning via ``ReasoningProvider`` (ADR-025)
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
are derived from the ReviewBundle (ADR-024).

A provider-agnostic reasoning runtime boundary (ADR-025) allows optional
provider-backed reasoning.  When a ``ReasoningProvider`` is supplied and
available, its output is integrated as candidate notes.  The default
``DisabledProvider`` preserves current behaviour — no live credentials
required.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas.findings import Finding
from reviewer.models import PullRequestContext, RepoSecurityProfile, ReviewBundle, ReviewConcern, ReviewMemory, ReviewObservation, ReviewPlan, ReviewTrace
from reviewer.providers import CandidateNote, DisabledProvider, ReasoningProvider, ReasoningRequest
from reviewer.provider_gate import ProviderGateResult, evaluate_provider_gate
from reviewer.repo_config import RepoConfig

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
from reviewer.observations import generate_observations, refine_observations
from reviewer.prompt_builder import build_reasoning_request


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
        provider_notes: Normalized candidate notes from the reasoning
            provider, after overlap suppression.  These are distinct from
            plan-driven notes, concerns, and observations.  Markdown-only,
            do not affect scoring.  See ADR-027.
        bundle: Structured review evidence gathered from PR delta,
            baseline, memory, and review plan.  Carries per-file context
            and review reasons.  Internal only — does not appear in the
            JSON contract.  See ADR-023.
        reasoning_request: The assembled reasoning request sent to the
            provider (if any).  Internal only — useful for debugging and
            testing the prompt assembly layer.  See ADR-025.
        provider_name: Name of the reasoning provider used (if any).
        provider_gate_result: Result of provider invocation gating
            (ADR-029).  Records whether the provider was invoked and
            the reasons for the decision.  None when no plan is
            available (legacy path) or provider is disabled.
        trace: Internal reviewer traceability record (ADR-030).
            Captures key signals about why the reviewer behaved the
            way it did.  Internal only — not in JSON contract.
    """

    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    concerns: list[ReviewConcern] = field(default_factory=list)
    observations: list[ReviewObservation] = field(default_factory=list)
    provider_notes: list[CandidateNote] = field(default_factory=list)
    bundle: ReviewBundle | None = None
    reasoning_request: ReasoningRequest | None = None
    provider_name: str = ""
    provider_gate_result: ProviderGateResult | None = None
    trace: ReviewTrace = field(default_factory=ReviewTrace)


def run_reasoning(
    ctx: PullRequestContext | dict[str, str],
    plan: ReviewPlan | None = None,
    provider: ReasoningProvider | None = None,
    deterministic_findings: list[Finding] | None = None,
    config: RepoConfig | None = None,
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

    When a ``ReasoningProvider`` is supplied and available (ADR-025),
    the assembled reasoning request is sent to the provider and its
    candidate notes are integrated into the result.  Provider invocation
    is gated by context richness (ADR-029) — the provider is only called
    when the PR context is rich or security-relevant enough to justify it.
    When the provider is disabled, unavailable, or gated out, the current
    heuristic-based flow runs unchanged.

    When a ``RepoConfig`` is supplied (ADR-041), low-signal and
    provider-skip path rules are applied:
    - Observations are suppressed for low-signal paths.
    - Provider reasoning is skipped when all non-excluded paths are
      in provider_skip_paths.

    Phase 1 behaviour:
    - produces contextual notes from the review plan or baseline overlap
    - surfaces relevant review memory as historical awareness
    - assembles a reasoning request when a plan and bundle are available
    - integrates provider candidate notes when provider is available
    - does not yet produce provider-generated findings
    - notes are informational and do not affect decision or risk_score

    Args:
        ctx: A ``PullRequestContext`` (preferred) or a legacy
            ``{path: content}`` dict.
        plan: An optional ``ReviewPlan`` that structures review focus.
            When provided, notes are derived from the plan.
        provider: An optional ``ReasoningProvider``.  When supplied and
            available, its output is integrated as candidate notes.
        deterministic_findings: Optional deterministic findings to include
            as context in the reasoning request.
        config: An optional ``RepoConfig`` (ADR-041).  Controls
            low-signal and provider-skip behavior.

    Returns:
        A ReasoningResult with contextual notes and (currently empty)
        findings.
    """
    if config is None:
        config = RepoConfig()
    # -- Normalise input --
    if isinstance(ctx, dict):
        ctx = PullRequestContext.from_dict(ctx)

    file_contents = ctx.pr_content.to_dict()
    notes: list[str] = []
    trace = ReviewTrace()

    if not file_contents:
        notes.append("No changed files provided for contextual review.")
        trace.entries.append("no changed files — early return")
        return ReasoningResult(findings=[], notes=notes, trace=trace)

    file_count = len(file_contents)
    notes.append(
        f"Contextual review examined {file_count} file(s)."
    )
    trace.entries.append(f"examining {file_count} file(s)")

    # -- Plan-driven contextual notes (ADR-021) --
    # -- Plan-driven contextual concerns (ADR-022) --
    # -- Review bundle assembly (ADR-023) --
    # -- Per-file review observations (ADR-024) --
    concerns: list[ReviewConcern] = []
    observations: list[ReviewObservation] = []
    provider_notes: list[CandidateNote] = []
    bundle: ReviewBundle | None = None
    reasoning_request: ReasoningRequest | None = None
    provider_name: str = ""
    gate_result: ProviderGateResult | None = None

    if plan is not None:
        trace.active_focus_areas = list(plan.focus_areas)
        trace.entries.append("plan available — plan-driven path")

        _add_plan_notes(notes, plan)
        concerns = generate_concerns(plan, ctx)
        trace.concern_count = len(concerns)

        bundle = build_review_bundle(ctx, plan)
        trace.bundle_item_count = bundle.item_count
        trace.bundle_high_focus_count = sum(
            1 for i in bundle.items
            if i.review_reason not in ("", "changed_file")
        )

        observations = generate_observations(bundle)
        # -- Low-signal path suppression (ADR-041) --
        if not config.is_empty:
            observations = [
                obs for obs in observations
                if not config.is_low_signal(obs.path)
            ]
        trace.observation_count = len(observations)
        trace.entries.append(
            f"generated {trace.concern_count} concern(s), "
            f"{trace.observation_count} observation(s)"
        )

        # -- Reasoning request assembly (ADR-025) --
        reasoning_request = build_reasoning_request(
            ctx=ctx,
            plan=plan,
            bundle=bundle,
            concerns=concerns,
            observations=observations,
            deterministic_findings=deterministic_findings,
        )

        # -- Provider invocation gating (ADR-029) --
        # -- Provider-skip paths (ADR-041) --
        # -- Provider-backed reasoning (ADR-025, ADR-027) --
        if provider is not None and provider.is_available():
            # Check provider_skip_paths before normal gate evaluation
            changed_paths = ctx.pr_content.paths
            if not config.is_empty and all(config.is_provider_skip(p) for p in changed_paths) and changed_paths:
                gate_result = ProviderGateResult(
                    should_invoke=False,
                    reasons=["skip: all changed paths match provider_skip_paths config"],
                )
                trace.provider_attempted = False
                trace.provider_gate_decision = "skipped"
                trace.provider_gate_reasons = list(gate_result.reasons)
                trace.entries.append("provider gate: skipped (provider_skip_paths config)")
            else:
                gate_result = evaluate_provider_gate(plan, bundle)
                trace.provider_gate_reasons = list(gate_result.reasons)
            if gate_result.should_invoke:
                trace.provider_attempted = True
                trace.provider_gate_decision = "invoked"
                trace.entries.append("provider gate: invoked")

                response = provider.reason(reasoning_request)
                provider_name = response.provider_name
                trace.provider_name = provider_name

                raw_count = len(response.structured_notes)
                trace.provider_notes_returned = raw_count

                # Suppress notes that overlap with existing context (ADR-027).
                provider_notes = _suppress_overlapping_notes(
                    response.structured_notes,
                    concerns=concerns,
                    observations=observations,
                    deterministic_findings=deterministic_findings,
                )
                trace.provider_notes_kept = len(provider_notes)
                trace.provider_notes_suppressed = raw_count - len(provider_notes)

                # -- Provider-backed observation refinement (ADR-028) --
                obs_before = len(observations)
                observations = refine_observations(observations, provider_notes)
                trace.observation_refinement_applied = True
                trace.observation_count = len(observations)
                trace.entries.append(
                    f"provider returned {raw_count} note(s), "
                    f"kept {trace.provider_notes_kept}, "
                    f"suppressed {trace.provider_notes_suppressed}"
                )
                if len(observations) != obs_before:
                    trace.entries.append(
                        f"observation refinement: {obs_before} → {len(observations)}"
                    )

                if response.candidate_notes:
                    notes.extend(response.candidate_notes)
            else:
                trace.provider_attempted = False
                trace.provider_gate_decision = "skipped"
                trace.entries.append("provider gate: skipped")
        elif provider is not None:
            trace.provider_gate_decision = "unavailable"
            trace.entries.append("provider unavailable")
        else:
            trace.provider_gate_decision = "disabled"
            trace.entries.append("provider disabled (none supplied)")
    else:
        trace.entries.append("no plan — legacy path")
        # Legacy path: derive notes directly from context overlap
        changed_paths = ctx.pr_content.paths
        if ctx.has_baseline and ctx.baseline_profile is not None:
            _add_baseline_notes(notes, changed_paths, ctx.baseline_profile)
        if ctx.has_memory and ctx.memory is not None:
            _add_memory_notes(notes, changed_paths, ctx.memory)

    return ReasoningResult(
        findings=[], notes=notes, concerns=concerns,
        observations=observations, provider_notes=provider_notes,
        bundle=bundle,
        reasoning_request=reasoning_request,
        provider_name=provider_name,
        provider_gate_result=gate_result,
        trace=trace,
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


# ======================================================================
# Overlap suppression for provider notes (ADR-027)
# ======================================================================

# Maximum provider notes to keep after suppression.
_MAX_PROVIDER_NOTES = 5


def _suppress_overlapping_notes(
    notes: list[CandidateNote],
    concerns: list[ReviewConcern] | None = None,
    observations: list[ReviewObservation] | None = None,
    deterministic_findings: list[Finding] | None = None,
) -> list[CandidateNote]:
    """Filter provider notes that overlap heavily with existing context.

    Uses keyword overlap to detect redundancy, plus content-quality filters
    to suppress notes that merely restate plan/baseline/memory metadata
    without adding file-specific security insight.

    The remaining notes are capped at ``_MAX_PROVIDER_NOTES``.

    See ADR-027 for the decision to introduce overlap suppression.
    """
    if not notes:
        return []

    # Build keyword sets from existing context.
    existing_keywords: set[str] = set()
    for c in (concerns or []):
        existing_keywords.update(_extract_keywords(c.title))
        existing_keywords.update(_extract_keywords(c.summary))
    for o in (observations or []):
        existing_keywords.update(_extract_keywords(o.title))
        existing_keywords.update(_extract_keywords(o.summary))
    for f in (deterministic_findings or []):
        existing_keywords.update(_extract_keywords(f.title))
        existing_keywords.update(_extract_keywords(f.description))

    kept: list[CandidateNote] = []
    for note in notes:
        # Content-quality filter: suppress notes with too-short summaries.
        if not note.summary or len(note.summary.strip()) < _MIN_NOTE_SUMMARY_LENGTH:
            continue
        # Content-quality filter: suppress notes that are metadata
        # restatements (file count, focus area lists, baseline context).
        if _is_metadata_restatement(note):
            continue
        note_keywords = (
            _extract_keywords(note.title) | _extract_keywords(note.summary)
        )
        if not note_keywords:
            continue
        # Skip overlap check if there are no existing keywords.
        if existing_keywords:
            overlap = note_keywords & existing_keywords
            overlap_ratio = len(overlap) / len(note_keywords)
            # Suppress if more than 60% of the note's keywords overlap.
            if overlap_ratio > 0.6:
                continue
        kept.append(note)

    return kept[:_MAX_PROVIDER_NOTES]


# Minimum summary length for a provider note to survive suppression.
_MIN_NOTE_SUMMARY_LENGTH = 15

# Phrases that indicate a note is restating pipeline metadata rather
# than providing file-specific security insight.
_METADATA_PHRASES = [
    "analysed",
    "analyzed",
    "changed file(s)",
    "review plan focuses",
    "review plan focus",
    "repository baseline context",
    "baseline context:",
    "review memory categories",
    "memory categories:",
    "deterministic finding(s) noted",
    "finding(s) noted as context",
]


def _is_metadata_restatement(note: CandidateNote) -> bool:
    """Return True if a note merely restates pipeline metadata.

    Catches notes that summarise file counts, restate plan focus areas,
    baseline frameworks, or memory categories without adding any
    file-specific security observation.
    """
    text = (note.summary or "").lower()
    title = (note.title or "").lower()
    combined = f"{title} {text}"
    for phrase in _METADATA_PHRASES:
        if phrase in combined:
            return True
    return False


# Stopwords excluded from keyword extraction.
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "this", "that", "these",
    "those", "it", "its", "of", "in", "to", "for", "with", "on", "at",
    "by", "from", "as", "or", "and", "but", "not", "no", "if", "so",
    "than", "too", "very", "just", "about", "into", "over", "after",
})


def _extract_keywords(text: str) -> set[str]:
    """Extract meaningful lowercase keywords from text.

    Strips short words and common stopwords to focus on content terms.
    """
    if not text:
        return set()
    words = set(text.lower().split())
    return {w.strip(".,;:!?\"'`()[]{}") for w in words if len(w) > 2} - _STOPWORDS
