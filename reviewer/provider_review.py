"""Provider-first structured review output for parity-zero (ADR-044).

Introduces structured provider review output — ``ProviderReviewItem`` — that
replaces loose candidate notes as the primary non-authoritative review surface.

The provider is now asked to return structured review judgments about changed
code.  parity-zero normalises, validates, deduplicates, and bounds the output
before surfacing it.

Key types:

- **ProviderReviewItem** — a single structured review judgment from the
  provider, richer than a free-form note.  Captures kind, category, title,
  summary, paths, confidence, evidence, and source.
- **ProviderReview** — the full normalised review output from a single
  provider invocation.

Trust boundaries (unchanged):
- Provider review items are **non-authoritative** — they do not create
  findings, affect scoring, or change the decision.
- Provider output remains candidate material.
- Only deterministic findings drive ScanResult and scoring.

See ADR-044 for the decision record.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Valid review item kinds — defines the vocabulary for provider output.
VALID_KINDS: frozenset[str] = frozenset({
    "candidate_finding",
    "candidate_observation",
    "review_attention",
})

# Valid categories from the findings taxonomy.
VALID_CATEGORIES: frozenset[str] = frozenset({
    "authentication",
    "authorization",
    "input_validation",
    "secrets",
    "insecure_configuration",
    "dependency_risk",
})

# Valid confidence levels — bounded, never "high" for provider output.
VALID_CONFIDENCES: frozenset[str] = frozenset({"low", "medium"})

# Maximum review items per provider invocation.
MAX_REVIEW_ITEMS = 8

# Minimum summary length to consider an item meaningful.
_MIN_SUMMARY_LENGTH = 15


@dataclass
class ProviderReviewItem:
    """A single structured review judgment from the provider.

    Richer than a ``CandidateNote`` — carries explicit kind, taxonomy
    category, evidence, and bounded confidence.

    Trust level: **non-authoritative**.  These are candidate review
    objects that inform the markdown output but do not create findings,
    affect scoring, or change the decision.
    """

    kind: str = "candidate_observation"
    """Review item kind: candidate_finding, candidate_observation, review_attention."""

    category: str = ""
    """Finding taxonomy category (when applicable), e.g. 'authentication'."""

    title: str = ""
    """Concise review item title."""

    summary: str = ""
    """Brief explanation of the security-relevant observation or concern."""

    paths: list[str] = field(default_factory=list)
    """Changed file paths this item relates to."""

    confidence: str = "low"
    """Provider confidence: 'low' or 'medium'. Never 'high' for provider output."""

    evidence: str = ""
    """Code-level evidence or rationale supporting this item."""

    source: str = "provider"
    """Origin of this item (e.g. 'github-models', 'anthropic', 'mock')."""


@dataclass
class ProviderReview:
    """The full normalised review output from a provider invocation.

    Contains zero or more validated ``ProviderReviewItem`` objects.
    """

    items: list[ProviderReviewItem] = field(default_factory=list)
    """Validated, normalised review items."""

    raw_item_count: int = 0
    """Number of items before validation/normalisation."""

    discarded_count: int = 0
    """Number of items discarded during validation."""

    provider_name: str = ""
    """Name of the provider that generated this output."""

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def has_items(self) -> bool:
        return bool(self.items)


# ======================================================================
# Parsing
# ======================================================================


def parse_provider_review_json(raw_text: str, provider_name: str = "") -> list[dict]:  # noqa: ARG001
    """Parse raw provider JSON text into a list of dicts.

    Supports:
    - JSON array of objects (preferred)
    - JSON array embedded in surrounding text (fallback)

    Returns an empty list on parse failure — fail safe.
    """
    text = raw_text.strip()
    if not text:
        return []

    # Try direct parse.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting a JSON array from within the text.
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict)]
        except (json.JSONDecodeError, ValueError):
            pass

    logger.debug("Failed to parse provider review JSON; returning empty list")
    return []


# ======================================================================
# Normalisation and validation
# ======================================================================


def normalize_review_item(raw: dict, provider_name: str = "") -> ProviderReviewItem | None:
    """Normalise a single raw dict into a ProviderReviewItem.

    Returns None for malformed items that cannot be salvaged.
    """
    title = str(raw.get("title", "")).strip()
    summary = str(raw.get("summary", "")).strip()

    # Must have at least a summary.
    if not summary and not title:
        return None
    if len(summary) < _MIN_SUMMARY_LENGTH and len(title) < _MIN_SUMMARY_LENGTH:
        return None

    # Kind — normalise to valid kind, default to candidate_observation.
    kind = str(raw.get("kind", raw.get("type", "candidate_observation"))).strip().lower()
    kind = kind.replace(" ", "_").replace("-", "_")
    if kind not in VALID_KINDS:
        kind = "candidate_observation"

    # Category — normalise to valid category or empty.
    category = str(raw.get("category", "")).strip().lower()
    category = category.replace(" ", "_").replace("-", "_")
    if category and category not in VALID_CATEGORIES:
        category = ""

    # Paths — normalise to list of non-empty strings.
    raw_paths = raw.get("paths", raw.get("files", []))
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths] if raw_paths else []
    elif not isinstance(raw_paths, list):
        raw_paths = []
    paths = [str(p).strip() for p in raw_paths if p and str(p).strip()]

    # Confidence — bounded to low/medium only.
    confidence = str(raw.get("confidence", "low")).strip().lower()
    if confidence not in VALID_CONFIDENCES:
        confidence = "low"

    # Evidence — optional.
    evidence = str(raw.get("evidence", raw.get("rationale", ""))).strip()

    return ProviderReviewItem(
        kind=kind,
        category=category,
        title=title or summary[:80],
        summary=summary or title,
        paths=paths,
        confidence=confidence,
        evidence=evidence,
        source=provider_name or "provider",
    )


def validate_and_normalize(
    raw_items: list[dict],
    provider_name: str = "",
) -> ProviderReview:
    """Validate and normalise a list of raw provider review dicts.

    - Invalid items are discarded.
    - Duplicates (same title + paths) are removed.
    - Output is capped at MAX_REVIEW_ITEMS.

    Returns a ProviderReview with validated items and counts.
    """
    raw_count = len(raw_items)
    items: list[ProviderReviewItem] = []
    seen: set[str] = set()

    for raw in raw_items:
        if len(items) >= MAX_REVIEW_ITEMS:
            break

        item = normalize_review_item(raw, provider_name)
        if item is None:
            continue

        # Deduplicate by title + sorted paths.
        dedup_key = f"{item.title.lower()}|{'|'.join(sorted(item.paths))}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        items.append(item)

    return ProviderReview(
        items=items,
        raw_item_count=raw_count,
        discarded_count=raw_count - len(items),
        provider_name=provider_name,
    )


def parse_and_validate_provider_review(
    raw_text: str,
    provider_name: str = "",
) -> ProviderReview:
    """End-to-end: parse raw provider JSON, validate, normalise, deduplicate.

    This is the canonical entry point for converting raw provider output
    into validated ``ProviderReviewItem`` objects.

    Always returns a valid ``ProviderReview`` — never raises on bad input.
    """
    raw_items = parse_provider_review_json(raw_text, provider_name)
    return validate_and_normalize(raw_items, provider_name)
