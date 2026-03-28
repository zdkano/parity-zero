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
- **GitHubModelsProvider** — first live reasoning provider using GitHub
  Models inference API (ADR-026).

Design principles:
- No live credentials required for tests or default flow.
- Current reviewer behavior is preserved when the provider is disabled.
- Provider output is *candidate* material — not trusted as proven findings
  by default (trust level is an explicit design dimension for later phases).
- The interface is future-compatible with GitHub Models, external LLMs,
  and other reasoning backends without requiring pipeline rework.

See ADR-025 for the decision record and ADR-026 for the GitHub Models
provider decision.
"""

from __future__ import annotations

import abc
import json
import logging
from dataclasses import dataclass, field

import httpx as _httpx_mod

logger = logging.getLogger(__name__)


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


# ======================================================================
# GitHub Models provider (first live provider — ADR-026)
# ======================================================================

# Default endpoint for the GitHub Models inference API.
_GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"

# Default model when none is configured explicitly.
_DEFAULT_MODEL = "openai/gpt-4o-mini"

# Request timeout in seconds.
_DEFAULT_TIMEOUT_SECONDS = 30

# Maximum number of candidate notes extracted from a single response.
_MAX_CANDIDATE_NOTES = 20

# System prompt that constrains the model to security-review candidate notes.
_SYSTEM_PROMPT = (
    "You are a security reviewer assistant for a GitHub pull request. "
    "Your task is to review the changed files and context provided, and "
    "produce concise, actionable security observations.\n\n"
    "Rules:\n"
    "- Focus on security implications of the changes described.\n"
    "- Each observation should be a single clear sentence or short paragraph.\n"
    "- Do not invent findings — only note what the provided context supports.\n"
    "- Do not assign severity or confidence scores.\n"
    "- Output ONLY a JSON array of strings, where each string is one observation.\n"
    "- If there are no meaningful security observations, return an empty array: []\n"
    "- Do not include any text outside the JSON array.\n"
)


def _format_user_prompt(request: ReasoningRequest) -> str:
    """Format a ReasoningRequest into a user prompt for the model.

    Produces a structured text summary of the PR context that the model
    can reason about.  Intentionally concise to stay within token limits.
    """
    sections: list[str] = []

    # -- Changed files --
    if request.changed_files_summary:
        file_lines = []
        for f in request.changed_files_summary[:20]:
            parts = [f.get("path", "unknown")]
            if f.get("review_reason"):
                parts.append(f"reason: {f['review_reason']}")
            if f.get("focus_areas"):
                parts.append(f"focus: {f['focus_areas']}")
            file_lines.append("  - " + ", ".join(parts))
        sections.append("Changed files:\n" + "\n".join(file_lines))

    # -- Plan context --
    if request.plan_focus_areas:
        sections.append(
            "Review focus areas: " + ", ".join(request.plan_focus_areas)
        )
    if request.plan_flags:
        sections.append("Review flags: " + ", ".join(request.plan_flags))
    if request.plan_guidance:
        sections.append(
            "Reviewer guidance:\n"
            + "\n".join(f"  - {g}" for g in request.plan_guidance[:5])
        )

    # -- Baseline context --
    if request.baseline_frameworks:
        sections.append(
            "Repository frameworks: " + ", ".join(request.baseline_frameworks)
        )
    if request.baseline_auth_patterns:
        sections.append(
            "Auth patterns in repo: " + ", ".join(request.baseline_auth_patterns)
        )

    # -- Memory context --
    if request.memory_categories:
        sections.append(
            "Prior review categories: " + ", ".join(request.memory_categories)
        )

    # -- Existing concerns --
    if request.existing_concerns:
        concern_lines = []
        for c in request.existing_concerns[:5]:
            concern_lines.append(
                f"  - [{c.get('category', '')}] {c.get('title', '')}: "
                f"{c.get('summary', '')}"
            )
        sections.append(
            "Existing review concerns:\n" + "\n".join(concern_lines)
        )

    # -- Existing observations --
    if request.existing_observations:
        obs_lines = []
        for o in request.existing_observations[:5]:
            obs_lines.append(
                f"  - {o.get('path', '')}: {o.get('title', '')} — "
                f"{o.get('summary', '')}"
            )
        sections.append(
            "Existing observations:\n" + "\n".join(obs_lines)
        )

    # -- Deterministic findings --
    if request.deterministic_findings_summary:
        det_lines = []
        for d in request.deterministic_findings_summary[:10]:
            det_lines.append(
                f"  - [{d.get('category', '')}] {d.get('title', '')} "
                f"in {d.get('file', '')}"
            )
        sections.append(
            "Deterministic findings already detected:\n"
            + "\n".join(det_lines)
        )

    if not sections:
        return "No context available for review."

    return "\n\n".join(sections)


def _parse_candidate_notes(raw_text: str) -> list[str]:
    """Parse candidate notes from the model response text.

    Expects a JSON array of strings.  Falls back to splitting by
    newlines if JSON parsing fails — the model may not always comply.
    """
    text = raw_text.strip()

    # Try JSON array parse first.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            notes = [
                str(item).strip()
                for item in parsed
                if isinstance(item, str) and item.strip()
            ]
            return notes[:_MAX_CANDIDATE_NOTES]
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: try to extract a JSON array from the response body.
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                notes = [
                    str(item).strip()
                    for item in parsed
                    if isinstance(item, str) and item.strip()
                ]
                return notes[:_MAX_CANDIDATE_NOTES]
        except (json.JSONDecodeError, ValueError):
            pass

    # Last resort: split non-empty lines, filter obvious non-content.
    lines = [
        line.strip().lstrip("- ").strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith(("{", "}", "[", "]"))
    ]
    return [l for l in lines if len(l) > 10][:_MAX_CANDIDATE_NOTES]


class GitHubModelsProvider(ReasoningProvider):
    """Live reasoning provider using the GitHub Models inference API (ADR-026).

    Sends a structured prompt to the GitHub Models endpoint (OpenAI-compatible
    chat completions API) and parses the response into candidate notes.

    Configuration:
    - ``token``: GitHub token for authentication (typically ``GITHUB_TOKEN``).
    - ``model``: Model identifier (default: ``openai/gpt-4o-mini``).
    - ``endpoint``: API base URL (default: GitHub Models endpoint).
    - ``timeout``: Request timeout in seconds (default: 30).

    Safety properties:
    - Returns an empty response on any error (network, timeout, parse).
    - Does not produce findings — only candidate notes.
    - Does not affect scoring or decision.
    - Is never required — callers can always fall back to DisabledProvider.

    Provider output is **candidate material only** — it does not become
    trusted findings.  See ADR-026 for the full decision record.
    """

    def __init__(
        self,
        token: str = "",
        model: str = "",
        endpoint: str = "",
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._token = token
        self._model = model or _DEFAULT_MODEL
        self._endpoint = (endpoint or _GITHUB_MODELS_ENDPOINT).rstrip("/")
        self._timeout = timeout

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        """Send the reasoning request to GitHub Models and return candidate notes.

        Any failure (network, timeout, invalid response) results in an
        empty response — the reviewer pipeline continues normally.
        """
        if not self.is_available():
            return self._empty_response()

        try:
            return self._call_model(request)
        except Exception:
            logger.warning(
                "GitHubModelsProvider: reasoning call failed; "
                "falling back to empty response.",
                exc_info=True,
            )
            return self._empty_response()

    def is_available(self) -> bool:
        """Available when a token is configured."""
        return bool(self._token)

    @property
    def name(self) -> str:
        return "github-models"

    # -- Internal helpers --

    def _empty_response(self) -> ReasoningResponse:
        return ReasoningResponse(
            candidate_notes=[],
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=False,
        )

    def _call_model(self, request: ReasoningRequest) -> ReasoningResponse:
        """Execute the HTTP call to the GitHub Models inference API."""
        user_prompt = _format_user_prompt(request)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        url = f"{self._endpoint}/chat/completions"

        response = _httpx_mod.post(
            url,
            json=payload,
            headers=headers,
            timeout=self._timeout,
        )
        response.raise_for_status()

        data = response.json()
        raw_content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

        if not raw_content:
            return self._empty_response()

        notes = _parse_candidate_notes(raw_content)

        return ReasoningResponse(
            candidate_notes=notes,
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=True,
        )
