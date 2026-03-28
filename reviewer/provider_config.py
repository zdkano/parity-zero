"""Provider configuration and resolution for parity-zero (ADR-026).

Reads minimal environment variables to determine which reasoning provider
to use at runtime.  The default is always ``DisabledProvider`` — live
reasoning requires explicit opt-in.

Environment variables:
- ``PARITY_REASONING_PROVIDER``:  Provider selection.
    - ``"disabled"`` (default) — no live reasoning, heuristic-only review.
    - ``"github-models"`` — use GitHub Models inference API.
- ``PARITY_REASONING_MODEL``: Model identifier for the provider.
    - Default: ``"openai/gpt-4o-mini"`` for GitHub Models.
- ``GITHUB_TOKEN``: Authentication token for GitHub Models.
    - Required when ``PARITY_REASONING_PROVIDER=github-models``.
    - Already available in GitHub Actions environments.

Design principles:
- No configuration framework — plain environment variables.
- Disabled by default — safe for local development and CI.
- Graceful fallback to DisabledProvider when config is incomplete.
- No import-time side effects — resolution happens when called.

See ADR-026 for the decision record.
"""

from __future__ import annotations

import logging
import os

from reviewer.providers import (
    DisabledProvider,
    GitHubModelsProvider,
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
