"""Provider-first structured review output for parity-zero (ADR-044, ADR-046).

Introduces structured provider review output — ``ProviderReviewItem`` — that
replaces loose candidate notes as the primary non-authoritative review surface.

The provider is now asked to return structured review judgments about changed
code.  parity-zero normalises, validates, deduplicates, and bounds the output
before surfacing it.

ADR-046 adds **post-parse evidence discipline** — after normalisation, items
are checked for speculative/weak content and either suppressed, softened to
``review_attention`` kind, or kept.  This reduces noise from:
- speculative missing-control claims without code evidence
- filename-only category guesses
- test/fixture noise
- weak non-security commentary

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

See ADR-044 for the decision record and ADR-046 for evidence discipline.
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

    Applies evidence-discipline filtering (ADR-046) after normalisation
    to suppress or soften speculative/weak items.

    Always returns a valid ``ProviderReview`` — never raises on bad input.
    """
    raw_items = parse_provider_review_json(raw_text, provider_name)
    review = validate_and_normalize(raw_items, provider_name)
    review = apply_evidence_discipline(review)
    return review


# ======================================================================
# Evidence discipline — post-parse filtering (ADR-046)
# ======================================================================

# Phrases that indicate a speculative missing-control claim without
# direct code evidence.  These are checked against title + summary.
_SPECULATIVE_MISSING_CONTROL_PHRASES = [
    "missing authorization",
    "missing authentication",
    "missing access control",
    "no authorization check",
    "no authentication check",
    "lacks authorization",
    "lacks authentication",
    "missing input validation",
    "missing validation check",
    "no input validation",
    "missing rate limit",
    "no rate limit",
    "missing csrf",
    "no csrf",
]

# Phrases indicating the item is acknowledging a positive control
# (good practice) — these are kept but bounded.
_POSITIVE_CONTROL_PHRASES = [
    "good practice",
    "properly implemented",
    "correctly validates",
    "appropriate use of",
    "secure implementation",
    "well-structured",
    "follows best practice",
]

# Path segments that identify test/fixture files.
_TEST_FIXTURE_SEGMENTS = frozenset({
    "test", "tests", "spec", "specs", "fixture", "fixtures",
    "__tests__", "__test__", "__mocks__", "mock", "mocks",
    "testdata", "test_data", "testutils", "test_utils",
    "conftest", "factories", "seeds", "stubs",
})

# Generic non-security phrases that indicate quality/product commentary
# rather than security review.
_NON_SECURITY_PHRASES = [
    "code quality",
    "code style",
    "naming convention",
    "documentation missing",
    "missing documentation",
    "missing comments",
    "code readability",
    "maintainability",
    "technical debt",
    "refactoring",
    "dead code",
    "unused import",
    "unused variable",
    "type annotation",
    "error message",
    "user experience",
    "performance issue",
    "performance optimization",
]


def apply_evidence_discipline(review: ProviderReview) -> ProviderReview:
    """Apply post-parse evidence-discipline rules to provider review items.

    Suppresses or softens items that are too speculative or weak (ADR-046):

    1. Speculative missing-control claims without evidence → softened to
       review_attention or suppressed.
    2. Filename-only category guesses (no evidence) → suppressed.
    3. Test/fixture noise → suppressed unless concrete security evidence.
    4. Weak non-security commentary → suppressed.
    5. Weak items with no evidence get confidence bounded to 'low'.
    6. Overlapping weak items on the same theme are collapsed.

    Returns a new ProviderReview with filtered items.
    """
    if not review.items:
        return review

    kept: list[ProviderReviewItem] = []
    suppressed = 0

    for item in review.items:
        result = _apply_item_discipline(item)
        if result is None:
            suppressed += 1
        else:
            kept.append(result)

    # Collapse overlapping weak items on similar themes.
    kept = _collapse_weak_duplicates(kept)

    return ProviderReview(
        items=kept,
        raw_item_count=review.raw_item_count,
        discarded_count=review.discarded_count + suppressed + (len(review.items) - suppressed - len(kept)),
        provider_name=review.provider_name,
    )


def _apply_item_discipline(item: ProviderReviewItem) -> ProviderReviewItem | None:
    """Apply evidence discipline to a single item.

    Returns:
        - The item (possibly softened) if it passes discipline checks.
        - None if the item should be suppressed.
    """
    combined_text = f"{item.title} {item.summary}".lower()
    evidence_text = (item.evidence or "").strip()

    # Rule 1: Suppress weak non-security commentary.
    if _is_non_security_commentary(combined_text):
        return None

    # Rule 2: Suppress test/fixture items unless they have concrete
    # security evidence.
    if _is_test_fixture_item(item) and not _has_concrete_security_evidence(item):
        return None

    # Rule 3: Handle speculative missing-control claims.
    if _is_speculative_missing_control(combined_text):
        if not evidence_text or len(evidence_text) < 20:
            # No meaningful evidence — suppress entirely.
            return None
        # Has some evidence — soften to review_attention with lower confidence.
        return ProviderReviewItem(
            kind="review_attention",
            category=item.category,
            title=_soften_title(item.title),
            summary=_soften_summary(item.summary),
            paths=item.paths,
            confidence="low",
            evidence=item.evidence,
            source=item.source,
        )

    # Rule 4: Suppress filename-only category guesses — items with a
    # category but no evidence and no meaningful summary beyond the filename.
    if item.category and not evidence_text and _is_filename_only_guess(item):
        return None

    # Rule 5: Bound confidence for items with no evidence.
    if not evidence_text and item.confidence != "low":
        item = ProviderReviewItem(
            kind=item.kind,
            category=item.category,
            title=item.title,
            summary=item.summary,
            paths=item.paths,
            confidence="low",
            evidence=item.evidence,
            source=item.source,
        )

    return item


def _is_non_security_commentary(text: str) -> bool:
    """Return True if the text is non-security quality/product commentary."""
    return any(phrase in text for phrase in _NON_SECURITY_PHRASES)


def _is_test_fixture_item(item: ProviderReviewItem) -> bool:
    """Return True if the item targets only test/fixture files."""
    if not item.paths:
        return False
    return all(_is_test_fixture_path(p) for p in item.paths)


def _is_test_fixture_path(path: str) -> bool:
    """Return True if a path looks like a test or fixture file."""
    segments = set(path.lower().replace("\\", "/").split("/"))
    return bool(segments & _TEST_FIXTURE_SEGMENTS)


def _has_concrete_security_evidence(item: ProviderReviewItem) -> bool:
    """Return True if a test/fixture item has concrete security evidence.

    Concrete evidence means the evidence field references actual security
    concerns like hardcoded credentials, exposed secrets, etc. — not just
    generic test-quality observations.
    """
    evidence = (item.evidence or "").lower()
    if len(evidence) < 20:
        return False
    security_indicators = [
        "password", "secret", "credential", "api_key", "api key",
        "token", "private_key", "private key", "hardcoded",
        "plaintext", "cleartext", "exposed", "injection",
        "sql injection", "xss", "command injection",
    ]
    return any(indicator in evidence for indicator in security_indicators)


def _is_speculative_missing_control(text: str) -> bool:
    """Return True if the text contains speculative missing-control claims."""
    return any(phrase in text for phrase in _SPECULATIVE_MISSING_CONTROL_PHRASES)


def _is_filename_only_guess(item: ProviderReviewItem) -> bool:
    """Return True if the item appears to be a category guess based only on filenames.

    Heuristic: summary is short and primarily references filenames or paths
    without substantive security content.
    """
    summary = item.summary.lower()
    # If summary is very short and mentions file paths, it's likely a guess.
    if len(summary) < 60:
        return True
    # Check if the summary primarily just names a file without analysis.
    path_mentions = sum(1 for p in item.paths if p.lower() in summary)
    # If the summary is mostly just path mentions, suppress it.
    words = summary.split()
    if len(words) < 8 and path_mentions > 0:
        return True
    return False


def _soften_title(title: str) -> str:
    """Convert an assertive title to review-attention phrasing."""
    lower = title.lower()
    for phrase in ("missing ", "no ", "lacks "):
        if lower.startswith(phrase):
            return "Verify " + title[len(phrase):]
    # Add "Verify" prefix for other assertion-style titles.
    if any(p in lower for p in _SPECULATIVE_MISSING_CONTROL_PHRASES):
        return title.replace("Missing", "Verify").replace("missing", "verify")
    return title


def _soften_summary(summary: str) -> str:
    """Convert assertive missing-control language to review-attention phrasing."""
    replacements = [
        ("is missing", "may need verification"),
        ("are missing", "may need verification"),
        ("lacks ", "may need "),
        ("does not have", "may not have"),
        ("no authorization", "authorization should be verified"),
        ("no authentication", "authentication should be verified"),
        ("no input validation", "input validation should be verified"),
        ("missing authorization", "authorization may need verification"),
        ("missing authentication", "authentication may need verification"),
        ("missing input validation", "input validation may need verification"),
    ]
    result = summary
    for old, new in replacements:
        result = result.replace(old, new)
    return result


def _collapse_weak_duplicates(items: list[ProviderReviewItem]) -> list[ProviderReviewItem]:
    """Collapse overlapping weak items on the same theme.

    When multiple review_attention or low-confidence items target similar
    categories and overlapping paths, keep only the strongest one.
    """
    if len(items) <= 1:
        return items

    kept: list[ProviderReviewItem] = []
    seen_themes: dict[str, int] = {}  # theme_key -> index in kept

    for item in items:
        theme_key = _theme_key(item)
        if theme_key in seen_themes:
            existing_idx = seen_themes[theme_key]
            existing = kept[existing_idx]
            # Keep the stronger item (higher confidence, more evidence).
            if _item_strength(item) > _item_strength(existing):
                kept[existing_idx] = item
        else:
            seen_themes[theme_key] = len(kept)
            kept.append(item)

    return kept


def _theme_key(item: ProviderReviewItem) -> str:
    """Generate a theme key for deduplication.

    Items with the same category and overlapping paths on review_attention
    or low-confidence items are considered the same theme.
    Only collapses items when both category and paths overlap meaningfully.
    """
    if item.kind not in ("review_attention",) and item.confidence != "low":
        # Stronger items get unique keys — don't collapse them.
        return f"{item.title.lower()}|{item.kind}|{'|'.join(sorted(item.paths))}"
    # Weak items: group by category + first path.
    # Items with no paths or no category get unique keys based on title
    # to avoid over-collapsing unrelated items.
    path_part = item.paths[0] if item.paths else ""
    if not item.category or not path_part:
        return f"weak|{item.category}|{path_part}|{item.title.lower()}"
    return f"weak|{item.category}|{path_part}"


def _item_strength(item: ProviderReviewItem) -> int:
    """Score item strength for comparison during deduplication."""
    score = 0
    if item.confidence == "medium":
        score += 2
    if item.kind == "candidate_finding":
        score += 3
    elif item.kind == "candidate_observation":
        score += 1
    if item.evidence and len(item.evidence) > 20:
        score += 2
    return score
