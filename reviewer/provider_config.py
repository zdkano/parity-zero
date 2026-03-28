"""Provider configuration and resolution for parity-zero (ADR-026, ADR-031).

Reads minimal environment variables to determine which reasoning provider
to use at runtime.  The default is always ``DisabledProvider`` — live
reasoning requires explicit opt-in.

Environment variables:
- ``PARITY_REASONING_PROVIDER``:  Provider selection.
    - ``"disabled"`` (default) — no live reasoning, heuristic-only review.
    - ``"github-models"`` — use GitHub Models inference API.
    - ``"anthropic"`` — use Anthropic Messages API.
    - ``"openai"`` — use OpenAI Chat Completions API.
- ``PARITY_REASONING_MODEL``: Model identifier for the provider.
    - Default: ``"openai/gpt-4o-mini"`` for GitHub Models.
    - Default: ``"claude-sonnet-4-20250514"`` for Anthropic.
    - Default: ``"gpt-4o-mini"`` for OpenAI.
- ``GITHUB_TOKEN``: Authentication token for GitHub Models.
    - Required when ``PARITY_REASONING_PROVIDER=github-models``.
    - Already available in GitHub Actions environments.
- ``ANTHROPIC_API_KEY``: API key for Anthropic.
    - Required when ``PARITY_REASONING_PROVIDER=anthropic``.
- ``OPENAI_API_KEY``: API key for OpenAI.
    - Required when ``PARITY_REASONING_PROVIDER=openai``.
- ``OPENAI_API_BASE``: Optional base URL override for OpenAI-compatible
    endpoints.

Design principles:
- No configuration framework — plain environment variables.
- Disabled by default — safe for local development and CI.
- Graceful fallback to DisabledProvider when config is incomplete.
- No import-time side effects — resolution happens when called.

See ADR-026 and ADR-031 for the decision records.
"""

from __future__ import annotations

import logging
import os

from reviewer.providers import (
    AnthropicProvider,
    DisabledProvider,
    GitHubModelsProvider,
    OpenAIProvider,
    ReasoningProvider,
)

logger = logging.getLogger(__name__)


def resolve_provider() -> ReasoningProvider:
    """Resolve the reasoning provider from environment configuration.

    Returns the appropriate ``ReasoningProvider`` based on the
    ``PARITY_REASONING_PROVIDER`` environment variable.  Falls back
    to ``DisabledProvider`` when the configuration is absent,
    incomplete, or unrecognised.

    Returns:
        A configured ``ReasoningProvider`` instance.
    """
    provider_name = os.getenv("PARITY_REASONING_PROVIDER", "disabled").strip().lower()

    if provider_name == "disabled" or not provider_name:
        return DisabledProvider()

    if provider_name == "github-models":
        return _resolve_github_models()

    if provider_name == "anthropic":
        return _resolve_anthropic()

    if provider_name == "openai":
        return _resolve_openai()

    logger.warning(
        "Unknown reasoning provider %r; falling back to disabled.",
        provider_name,
    )
    return DisabledProvider()


def _resolve_github_models() -> ReasoningProvider:
    """Build a GitHubModelsProvider from environment configuration.

    Falls back to DisabledProvider if required credentials are missing.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        logger.warning(
            "PARITY_REASONING_PROVIDER=github-models but GITHUB_TOKEN is "
            "not set; falling back to disabled provider."
        )
        return DisabledProvider()

    model = os.getenv("PARITY_REASONING_MODEL", "")

    return GitHubModelsProvider(
        token=token,
        model=model,
    )


def _resolve_anthropic() -> ReasoningProvider:
    """Build an AnthropicProvider from environment configuration.

    Falls back to DisabledProvider if required credentials are missing.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.warning(
            "PARITY_REASONING_PROVIDER=anthropic but ANTHROPIC_API_KEY is "
            "not set; falling back to disabled provider."
        )
        return DisabledProvider()

    model = os.getenv("PARITY_REASONING_MODEL", "")

    return AnthropicProvider(
        api_key=api_key,
        model=model,
    )


def _resolve_openai() -> ReasoningProvider:
    """Build an OpenAIProvider from environment configuration.

    Falls back to DisabledProvider if required credentials are missing.
    Supports optional ``OPENAI_API_BASE`` for OpenAI-compatible endpoints.
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning(
            "PARITY_REASONING_PROVIDER=openai but OPENAI_API_KEY is "
            "not set; falling back to disabled provider."
        )
        return DisabledProvider()

    model = os.getenv("PARITY_REASONING_MODEL", "")
    endpoint = os.getenv("OPENAI_API_BASE", "")

    return OpenAIProvider(
        api_key=api_key,
        model=model,
        endpoint=endpoint,
    )
