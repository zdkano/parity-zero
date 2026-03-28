"""Provider-agnostic reasoning runtime interface for parity-zero (ADR-025).

Defines the boundary between the reviewer pipeline and external reasoning
providers (e.g. GitHub Models, external LLMs).  The interface is deliberately
minimal — it specifies what a reasoning provider receives and what it returns,
without prescribing how the provider operates internally.

Key types:

- **ReasoningRequest** — structured input assembled from the reviewer
  pipeline context (plan, bundle, baseline, memory, deterministic findings).
- **ReasoningResponse** — structured output that the reviewer pipeline
  can consume and integrate into its existing flow.
- **ReasoningProvider** — abstract base defining the provider contract.
- **DisabledProvider** — no-op provider used when reasoning is not enabled.
- **MockProvider** — predictable provider for testing and local development.

Design principles:
- No live credentials required for tests or default flow.
- Current reviewer behavior is preserved when the provider is disabled.
- Provider output is *candidate* material — not trusted as proven findings
  by default (trust level is an explicit design dimension for later phases).
- The interface is future-compatible with GitHub Models, external LLMs,
  and other reasoning backends without requiring pipeline rework.

See ADR-025 for the decision record.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


# ======================================================================
# Reasoning request / response
# ======================================================================


@dataclass
class ReasoningRequest:
    """Structured input to a reasoning provider.

    Assembled by the prompt builder from the reviewer pipeline context.
    Each field carries a specific slice of context that the provider can
    use when reasoning about the PR's security implications.

    The request is **not** a raw prompt string — it is structured data
    that a provider adapter can format according to its own conventions.
    """

    changed_files_summary: list[dict[str, str]] = field(default_factory=list)
    """Per-file summaries: each dict has 'path', 'review_reason', 'focus_areas'."""

    plan_focus_areas: list[str] = field(default_factory=list)
    """Finding categories the review plan considers relevant."""

    plan_flags: list[str] = field(default_factory=list)
    """Elevated attention flags from the review plan."""

    plan_guidance: list[str] = field(default_factory=list)
    """Accumulated reviewer guidance from the plan."""

    baseline_frameworks: list[str] = field(default_factory=list)
    """Frameworks detected in the repository baseline."""

    baseline_auth_patterns: list[str] = field(default_factory=list)
    """Auth patterns detected in the repository baseline."""

    memory_categories: list[str] = field(default_factory=list)
    """Historical review memory categories relevant to this PR."""

    memory_entries: list[dict[str, str]] = field(default_factory=list)
    """Relevant memory entries: each dict has 'category', 'summary'."""

    existing_concerns: list[dict[str, str]] = field(default_factory=list)
    """Pre-existing review concerns: each dict has 'category', 'title', 'summary'."""

    existing_observations: list[dict[str, str]] = field(default_factory=list)
    """Pre-existing observations: each dict has 'path', 'title', 'summary'."""

    deterministic_findings_summary: list[dict[str, str]] = field(default_factory=list)
    """Deterministic findings for context: each dict has 'category', 'title', 'file'."""

    @property
    def file_count(self) -> int:
        """Number of changed files in the request."""
        return len(self.changed_files_summary)

    @property
    def has_plan_context(self) -> bool:
        """Whether the request carries plan-derived context."""
        return bool(self.plan_focus_areas or self.plan_flags)

    @property
    def has_baseline_context(self) -> bool:
        """Whether the request carries baseline repository context."""
        return bool(self.baseline_frameworks or self.baseline_auth_patterns)

    @property
    def has_memory_context(self) -> bool:
        """Whether the request carries review memory context."""
        return bool(self.memory_categories or self.memory_entries)


@dataclass
class ReasoningResponse:
    """Structured output from a reasoning provider.

    The response carries candidate notes and (optionally) candidate
    findings that the reviewer pipeline can integrate.  Provider output
    is treated as *candidate* material — the pipeline decides what to
    trust and surface.

    Phase 1: provider output produces candidate notes only.  Candidate
    findings are a future capability once trust calibration is in place.
    """

    candidate_notes: list[str] = field(default_factory=list)
    """Reasoning-generated contextual notes for the PR summary."""

    candidate_findings: list[dict[str, str]] = field(default_factory=list)
    """Reasoning-generated candidate findings (future use, empty in Phase 1)."""

    provider_name: str = ""
    """Name of the provider that generated this response."""

    is_from_live_provider: bool = False
    """Whether this response came from a live (non-mock, non-disabled) provider."""

    @property
    def has_content(self) -> bool:
        """Whether the response carries any content."""
        return bool(self.candidate_notes or self.candidate_findings)


# ======================================================================
# Provider interface
# ======================================================================


class ReasoningProvider(abc.ABC):
    """Abstract base for reasoning providers.

    Each provider implementation adapts the structured ``ReasoningRequest``
    to its own reasoning backend and returns a ``ReasoningResponse``.

    Implementations should:
    - not require live credentials at import time
    - return an empty/graceful response when unavailable
    - set ``provider_name`` and ``is_from_live_provider`` on the response
    """

    @abc.abstractmethod
    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        """Run reasoning against the given request.

        Args:
            request: Structured reasoning input from the prompt builder.

        Returns:
            Structured reasoning output for pipeline integration.
        """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Whether this provider is currently available for reasoning.

        Returns False when credentials are missing, the service is
        unreachable, or the provider is explicitly disabled.
        """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""


# ======================================================================
# Disabled provider (default)
# ======================================================================


class DisabledProvider(ReasoningProvider):
    """No-op reasoning provider used when reasoning is not enabled.

    Returns an empty response — the reviewer pipeline continues with
    its existing heuristic-based flow.  This is the default provider.
    """

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        return ReasoningResponse(
            candidate_notes=[],
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=False,
        )

    def is_available(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "disabled"


# ======================================================================
# Mock provider (testing / local development)
# ======================================================================


class MockProvider(ReasoningProvider):
    """Predictable reasoning provider for testing and local development.

    Returns structured, deterministic output based on the request contents.
    Useful for:
    - verifying pipeline integration without live credentials
    - testing that provider output flows correctly through the pipeline
    - local development with realistic-looking reasoning output

    The mock provider does **not** generate findings — it only produces
    candidate notes, consistent with Phase 1 trust boundaries.
    """

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        notes: list[str] = []

        notes.append(
            f"[mock-reasoning] Analysed {request.file_count} changed file(s)."
        )

        if request.has_plan_context:
            areas = ", ".join(request.plan_focus_areas[:3])
            notes.append(
                f"[mock-reasoning] Review plan focuses on: {areas}."
            )

        if request.has_baseline_context:
            frameworks = ", ".join(request.baseline_frameworks[:3])
            notes.append(
                f"[mock-reasoning] Repository baseline context: {frameworks}."
            )

        if request.has_memory_context:
            cats = ", ".join(request.memory_categories[:3])
            notes.append(
                f"[mock-reasoning] Review memory categories: {cats}."
            )

        if request.deterministic_findings_summary:
            count = len(request.deterministic_findings_summary)
            notes.append(
                f"[mock-reasoning] {count} deterministic finding(s) noted as context."
            )

        return ReasoningResponse(
            candidate_notes=notes,
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=False,
        )

    def is_available(self) -> bool:
        return True

    @property
    def name(self) -> str:
        return "mock"
