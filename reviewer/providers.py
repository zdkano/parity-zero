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
- **AnthropicProvider** — live reasoning provider using the Anthropic
  Messages API (ADR-031).
- **OpenAIProvider** — live reasoning provider using the OpenAI Chat
  Completions API (ADR-031).

Design principles:
- No live credentials required for tests or default flow.
- Current reviewer behavior is preserved when the provider is disabled.
- Provider output is *candidate* material — not trusted as proven findings
  by default (trust level is an explicit design dimension for later phases).
- The interface is future-compatible with GitHub Models, external LLMs,
  and other reasoning backends without requiring pipeline rework.

See ADR-025 for the decision record, ADR-026 for the GitHub Models
provider decision, ADR-027 for the provider output quality pass, and
ADR-031 for the Anthropic and OpenAI provider decisions.
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
class CandidateNote:
    """Normalized internal structure for a provider-generated candidate note.

    Candidate notes are provider output that has been shaped into a
    consistent internal form for deduplication, prioritisation, and
    markdown rendering.  They remain non-authoritative candidate
    material and do not appear in the ScanResult JSON contract.

    See ADR-027 for the decision to normalize provider output.
    """

    title: str = ""
    """Concise note title (one line)."""

    summary: str = ""
    """Brief explanation of the security-relevant observation."""

    related_paths: list[str] = field(default_factory=list)
    """Changed file paths this note relates to."""

    confidence: str = "low"
    """How confident the provider is (low/medium — never high for candidate notes)."""

    source: str = ""
    """Origin of this note (e.g. 'github-models', 'mock')."""


@dataclass
class ReasoningResponse:
    """Structured output from a reasoning provider.

    The response carries candidate notes and (optionally) candidate
    findings that the reviewer pipeline can integrate.  Provider output
    is treated as *candidate* material — the pipeline decides what to
    trust and surface.

    Phase 1: provider output produces candidate notes only.  Candidate
    findings are a future capability once trust calibration is in place.

    ``structured_notes`` carry normalized ``CandidateNote`` objects
    for dedup and rendering.  ``candidate_notes`` remains as a flat
    string list for backward compatibility.
    """

    candidate_notes: list[str] = field(default_factory=list)
    """Reasoning-generated contextual notes for the PR summary."""

    structured_notes: list[CandidateNote] = field(default_factory=list)
    """Normalized candidate notes with title, summary, paths, confidence."""

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
        structured: list[CandidateNote] = []

        paths = [f.get("path", "") for f in request.changed_files_summary[:5]]

        # Per-file security-relevant notes (up to 3 files).
        for f_info in request.changed_files_summary[:3]:
            path = f_info.get("path", "")
            focus = f_info.get("focus_areas", "")
            if focus:
                summary = (
                    f"{path} may warrant closer review for {focus} patterns; "
                    f"consider verifying edge cases and error handling paths."
                )
            else:
                summary = (
                    f"{path} was changed; consider reviewing for input "
                    f"validation and secure defaults."
                )
            notes.append(f"[mock-reasoning] {summary}")
            structured.append(CandidateNote(
                title=f"Security review scope for {path}",
                summary=summary,
                related_paths=[path],
                confidence="low",
                source="mock",
            ))

        # Cross-file count note.
        count_summary = (
            f"Reviewed {request.file_count} changed file(s); consider "
            f"whether interactions between modified files introduce "
            f"security-relevant state changes."
        )
        notes.append(f"[mock-reasoning] {count_summary}")
        structured.append(CandidateNote(
            title=f"Cross-file review ({request.file_count} changed file(s))",
            summary=count_summary,
            related_paths=paths,
            confidence="low",
            source="mock",
        ))

        # Plan context — tied to the first changed file when available.
        if request.has_plan_context:
            areas = ", ".join(request.plan_focus_areas[:3])
            target = paths[0] if paths else "this PR"
            summary = (
                f"{target} is flagged for {areas} review; consider whether "
                f"access control and validation patterns are consistent "
                f"with repository conventions."
            )
            notes.append(f"[mock-reasoning] {summary}")
            structured.append(CandidateNote(
                title=f"Review focus alignment for {target}",
                summary=summary,
                related_paths=paths[:1],
                confidence="low",
                source="mock",
            ))

        # Baseline context — framework-specific guidance.
        if request.has_baseline_context:
            frameworks = ", ".join(request.baseline_frameworks[:3])
            target = paths[0] if paths else "this PR"
            summary = (
                f"{target} operates in a {frameworks} context; consider "
                f"verifying that framework-specific security middleware "
                f"and defaults are applied correctly."
            )
            notes.append(f"[mock-reasoning] {summary}")
            structured.append(CandidateNote(
                title=f"Framework context for {target} ({frameworks})",
                summary=summary,
                related_paths=paths[:1],
                confidence="low",
                source="mock",
            ))

        # Memory context — prior concern recurrence.
        if request.has_memory_context:
            cats = ", ".join(request.memory_categories[:3])
            target = paths[0] if paths else "this PR"
            summary = (
                f"Review history notes prior concerns about {cats} in "
                f"similar areas; {target} may exhibit related patterns "
                f"worth re-checking."
            )
            notes.append(f"[mock-reasoning] {summary}")
            structured.append(CandidateNote(
                title=f"Prior review pattern recurrence in {target}",
                summary=summary,
                related_paths=paths[:1],
                confidence="low",
                source="mock",
            ))

        # Deterministic findings — cross-reference with changed files.
        if request.deterministic_findings_summary:
            finding = request.deterministic_findings_summary[0]
            finding_file = finding.get("file", "unknown")
            finding_cat = finding.get("category", "security")
            count = len(request.deterministic_findings_summary)
            target = paths[0] if paths else "this PR"
            summary = (
                f"Deterministic checks flagged {count} issue(s) including "
                f"{finding_cat} concerns in {finding_file}; consider "
                f"whether {target} has related patterns that may need "
                f"attention."
            )
            notes.append(f"[mock-reasoning] {summary}")
            structured.append(CandidateNote(
                title=f"Contextual review of deterministic signals in {target}",
                summary=summary,
                related_paths=[finding_file] + paths[:1],
                confidence="low",
                source="mock",
            ))

        return ReasoningResponse(
            candidate_notes=notes,
            structured_notes=structured,
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

# Maximum candidate notes extracted from a single response (parsing-stage cap).
# Further reduced to _MAX_PROVIDER_NOTES (5) after overlap suppression.
_MAX_CANDIDATE_NOTES = 10

# System prompt that constrains the model to security-review candidate notes.
_SYSTEM_PROMPT = (
    "You are an experienced security code reviewer assisting with a GitHub "
    "pull request review.  You have access to contextual information about "
    "the repository and the specific changes being reviewed.\n\n"
    "Your role:\n"
    "- Produce concise, security-relevant observations about the changed code.\n"
    "- Focus on what the specific changes introduce or expose.\n"
    "- Be file-specific: tie each observation to the relevant changed file(s).\n"
    "- Reference concrete code patterns, functions, or configurations.\n"
    "- Express genuine uncertainty — say 'may', 'could', 'worth verifying' "
    "when you are not certain.\n\n"
    "Do NOT:\n"
    "- Restate deterministic findings already listed in the context.\n"
    "- Repeat concerns or observations already provided.\n"
    "- Restate context metadata (file counts, focus areas, baseline "
    "frameworks, or memory categories) — these are already known.\n"
    "- Produce generic security best-practice advice unrelated to the changes.\n"
    "- Summarise what was analysed — only provide new observations.\n"
    "- Exaggerate risk — do not claim vulnerabilities without evidence.\n"
    "- Assign severity or confidence scores.\n\n"
    "Output format:\n"
    "Return ONLY a JSON array of objects.  Each object must have:\n"
    '  {"title": "<short title>", "summary": "<1-2 sentence observation>", '
    '"paths": ["<related file path(s)>"], "confidence": "low" or "medium"}\n'
    "If there are no meaningful security observations, return an empty array: []\n"
    "Do not include any text outside the JSON array.\n"
)


def _format_user_prompt(request: ReasoningRequest) -> str:
    """Format a ReasoningRequest into a user prompt for the model.

    Produces a structured text summary of the PR context that the model
    can reason about.  Intentionally concise to stay within token limits.
    Includes explicit context about what has already been detected to
    reduce redundant output.
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

    # -- Already-detected context (to reduce redundancy) --
    already_detected: list[str] = []

    if request.existing_concerns:
        concern_lines = []
        for c in request.existing_concerns[:5]:
            concern_lines.append(
                f"  - [{c.get('category', '')}] {c.get('title', '')}: "
                f"{c.get('summary', '')}"
            )
        already_detected.append(
            "Review concerns already raised:\n" + "\n".join(concern_lines)
        )

    if request.existing_observations:
        obs_lines = []
        for o in request.existing_observations[:5]:
            obs_lines.append(
                f"  - {o.get('path', '')}: {o.get('title', '')}"
            )
        already_detected.append(
            "Observations already noted:\n" + "\n".join(obs_lines)
        )

    if request.deterministic_findings_summary:
        det_lines = []
        for d in request.deterministic_findings_summary[:10]:
            det_lines.append(
                f"  - [{d.get('category', '')}] {d.get('title', '')} "
                f"in {d.get('file', '')}"
            )
        already_detected.append(
            "Deterministic findings already detected (do NOT restate these):\n"
            + "\n".join(det_lines)
        )

    if already_detected:
        sections.append(
            "ALREADY DETECTED (do not repeat or restate):\n"
            + "\n".join(already_detected)
        )

    if not sections:
        return "No context available for review."

    return "\n\n".join(sections)


def _parse_candidate_notes(raw_text: str, provider_name: str = "") -> list[CandidateNote]:
    """Parse candidate notes from the model response text.

    Supports two formats:
    1. JSON array of objects with title/summary/paths/confidence fields
       (preferred — matches the updated system prompt).
    2. JSON array of strings (backward-compatible fallback).

    Falls back to line splitting if JSON parsing fails entirely.
    """
    text = raw_text.strip()
    if not text:
        return []

    # Try JSON parse first.
    parsed = _try_json_parse(text)
    if parsed is not None and isinstance(parsed, list):
        return _normalize_parsed_notes(parsed, provider_name)

    # Fallback: try to extract a JSON array from the response body.
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        parsed = _try_json_parse(text[start : end + 1])
        if parsed is not None and isinstance(parsed, list):
            return _normalize_parsed_notes(parsed, provider_name)

    # Last resort: split non-empty lines, filter obvious non-content.
    lines = [
        line.strip().lstrip("- ").strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith(("{", "}", "[", "]"))
    ]
    return [
        CandidateNote(
            title=text[:80],
            summary=text,
            confidence="low",
            source=provider_name,
        )
        for text in lines if len(text) > 10
    ][:_MAX_CANDIDATE_NOTES]


def _try_json_parse(text: str):
    """Attempt JSON parse, returning None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _normalize_parsed_notes(
    items: list, provider_name: str = "",
) -> list[CandidateNote]:
    """Normalize a parsed JSON array into CandidateNote objects.

    Handles both object items (structured) and string items (flat).
    """
    notes: list[CandidateNote] = []
    for item in items:
        if len(notes) >= _MAX_CANDIDATE_NOTES:
            break
        if isinstance(item, dict):
            title = str(item.get("title", "")).strip()
            summary = str(item.get("summary", "")).strip()
            if not summary and not title:
                continue
            paths = item.get("paths", [])
            if isinstance(paths, str):
                paths = [paths] if paths else []
            elif not isinstance(paths, list):
                paths = []
            confidence = str(item.get("confidence", "low")).strip().lower()
            if confidence not in ("low", "medium"):
                confidence = "low"
            notes.append(CandidateNote(
                title=title or summary[:80],
                summary=summary or title,
                related_paths=[str(p) for p in paths if p],
                confidence=confidence,
                source=provider_name,
            ))
        elif isinstance(item, str) and item.strip():
            text = item.strip()
            notes.append(CandidateNote(
                title=text[:80],
                summary=text,
                confidence="low",
                source=provider_name,
            ))
    return notes


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

        structured = _parse_candidate_notes(raw_content, provider_name=self.name)
        flat_notes = [n.summary for n in structured]

        return ReasoningResponse(
            candidate_notes=flat_notes,
            structured_notes=structured,
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=True,
        )


# ======================================================================
# Anthropic provider (ADR-031)
# ======================================================================

# Default endpoint for the Anthropic Messages API.
_ANTHROPIC_ENDPOINT = "https://api.anthropic.com"

# Default model for the Anthropic provider.
_ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Anthropic API version header.
_ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider(ReasoningProvider):
    """Live reasoning provider using the Anthropic Messages API (ADR-031).

    Sends a structured prompt to the Anthropic Messages endpoint and parses
    the response into candidate notes.

    Configuration:
    - ``api_key``: Anthropic API key (``ANTHROPIC_API_KEY``).
    - ``model``: Model identifier (default: ``claude-sonnet-4-20250514``).
    - ``endpoint``: API base URL (default: Anthropic production endpoint).
    - ``timeout``: Request timeout in seconds (default: 30).

    Safety properties:
    - Returns an empty response on any error (network, timeout, parse).
    - Does not produce findings — only candidate notes.
    - Does not affect scoring or decision.
    - Is never required — callers can always fall back to DisabledProvider.

    Provider output is **candidate material only** — it does not become
    trusted findings.  See ADR-031 for the full decision record.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        endpoint: str = "",
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._model = model or _ANTHROPIC_DEFAULT_MODEL
        self._endpoint = (endpoint or _ANTHROPIC_ENDPOINT).rstrip("/")
        self._timeout = timeout

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        """Send the reasoning request to Anthropic and return candidate notes.

        Any failure (network, timeout, invalid response) results in an
        empty response — the reviewer pipeline continues normally.
        """
        if not self.is_available():
            return self._empty_response()

        try:
            return self._call_model(request)
        except Exception:
            logger.warning(
                "AnthropicProvider: reasoning call failed; "
                "falling back to empty response.",
                exc_info=True,
            )
            return self._empty_response()

    def is_available(self) -> bool:
        """Available when an API key is configured."""
        return bool(self._api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    # -- Internal helpers --

    def _empty_response(self) -> ReasoningResponse:
        return ReasoningResponse(
            candidate_notes=[],
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=False,
        )

    def _call_model(self, request: ReasoningRequest) -> ReasoningResponse:
        """Execute the HTTP call to the Anthropic Messages API."""
        user_prompt = _format_user_prompt(request)

        payload = {
            "model": self._model,
            "max_tokens": 1024,
            "system": _SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        }

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_API_VERSION,
            "Content-Type": "application/json",
        }

        url = f"{self._endpoint}/v1/messages"

        response = _httpx_mod.post(
            url,
            json=payload,
            headers=headers,
            timeout=self._timeout,
        )
        response.raise_for_status()

        data = response.json()
        # Anthropic Messages API returns content as a list of blocks.
        content_blocks = data.get("content", [])
        raw_content = ""
        for block in content_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                raw_content += block.get("text", "")

        if not raw_content:
            return self._empty_response()

        structured = _parse_candidate_notes(raw_content, provider_name=self.name)
        flat_notes = [n.summary for n in structured]

        return ReasoningResponse(
            candidate_notes=flat_notes,
            structured_notes=structured,
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=True,
        )


# ======================================================================
# OpenAI provider (ADR-031)
# ======================================================================

# Default endpoint for the OpenAI Chat Completions API.
_OPENAI_ENDPOINT = "https://api.openai.com/v1"

# Default model for the OpenAI provider.
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(ReasoningProvider):
    """Live reasoning provider using the OpenAI Chat Completions API (ADR-031).

    Sends a structured prompt to the OpenAI chat completions endpoint and
    parses the response into candidate notes.  The API shape is compatible
    with OpenAI-compatible third-party endpoints (use ``endpoint`` to
    override the base URL).

    Configuration:
    - ``api_key``: OpenAI API key (``OPENAI_API_KEY``).
    - ``model``: Model identifier (default: ``gpt-4o-mini``).
    - ``endpoint``: API base URL (default: OpenAI production endpoint).
    - ``timeout``: Request timeout in seconds (default: 30).

    Safety properties:
    - Returns an empty response on any error (network, timeout, parse).
    - Does not produce findings — only candidate notes.
    - Does not affect scoring or decision.
    - Is never required — callers can always fall back to DisabledProvider.

    Provider output is **candidate material only** — it does not become
    trusted findings.  See ADR-031 for the full decision record.
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        endpoint: str = "",
        timeout: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._model = model or _OPENAI_DEFAULT_MODEL
        self._endpoint = (endpoint or _OPENAI_ENDPOINT).rstrip("/")
        self._timeout = timeout

    def reason(self, request: ReasoningRequest) -> ReasoningResponse:
        """Send the reasoning request to OpenAI and return candidate notes.

        Any failure (network, timeout, invalid response) results in an
        empty response — the reviewer pipeline continues normally.
        """
        if not self.is_available():
            return self._empty_response()

        try:
            return self._call_model(request)
        except Exception:
            logger.warning(
                "OpenAIProvider: reasoning call failed; "
                "falling back to empty response.",
                exc_info=True,
            )
            return self._empty_response()

    def is_available(self) -> bool:
        """Available when an API key is configured."""
        return bool(self._api_key)

    @property
    def name(self) -> str:
        return "openai"

    # -- Internal helpers --

    def _empty_response(self) -> ReasoningResponse:
        return ReasoningResponse(
            candidate_notes=[],
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=False,
        )

    def _call_model(self, request: ReasoningRequest) -> ReasoningResponse:
        """Execute the HTTP call to the OpenAI Chat Completions API."""
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
            "Authorization": f"Bearer {self._api_key}",
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

        structured = _parse_candidate_notes(raw_content, provider_name=self.name)
        flat_notes = [n.summary for n in structured]

        return ReasoningResponse(
            candidate_notes=flat_notes,
            structured_notes=structured,
            candidate_findings=[],
            provider_name=self.name,
            is_from_live_provider=True,
        )
