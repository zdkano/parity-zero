"""Markdown summary formatter for parity-zero PR output.

Converts a ScanResult into a developer-friendly markdown summary suitable
for posting as a GitHub PR comment.

Output hierarchy reflects the provider-first review model (ADR-045, ADR-047):

1. Deterministic findings — authoritative, drive scoring.
2. Short deterministic change summary — factual "what changed" (ADR-047).
3. Provider security review — primary non-authoritative review surface.
   When present, this is the main explanatory/review layer.
4. Heuristic concerns/observations — shown only as minimal fallback
   when provider review is absent or as unique high-value support signals.

When provider review is present and has items, heuristic concern and
observation sections are suppressed to avoid stacked competing review
voices.  The user perceives one main reviewer (the provider), with
parity-zero acting as the control/normalization/trust framework.

Legacy provider candidate notes are suppressed whenever structured
provider review items are present.

Design goals (from team.md):
  - clear, practical, and low-noise
  - actionable recommendations
  - minimal workflow disruption

The markdown output is a *presentation* layer.  The structured JSON
ScanResult remains the authoritative system contract.
"""

from __future__ import annotations

from reviewer.models import ReviewConcern, ReviewObservation
from reviewer.provider_review import ProviderReview, ProviderReviewItem
from reviewer.providers import CandidateNote
from schemas.findings import Decision, ScanResult, Severity

_DECISION_BADGES: dict[Decision, str] = {
    Decision.PASS: "✅ Pass",
    Decision.WARN: "⚠️ Warn",
    Decision.BLOCK: "🚫 Block",
}


def _risk_bar(score: int) -> str:
    """Return a compact text bar representing the risk score (0–100)."""
    filled = round(score / 10)
    empty = 10 - filled
    return f"`[{'█' * filled}{'░' * empty}]` **{score}/100**"


def format_markdown(
    result: ScanResult,
    concerns: list[ReviewConcern] | None = None,
    observations: list[ReviewObservation] | None = None,
    provider_notes: list[CandidateNote] | None = None,
    provider_review: ProviderReview | None = None,
    change_summary_bullets: list[str] | None = None,
) -> str:
    """Render a ScanResult as a markdown PR summary.

    The output hierarchy is (ADR-045, ADR-047):
    1. Deterministic findings (authoritative)
    2. Short deterministic change summary (what changed — ADR-047)
    3. Provider security review (primary non-authoritative review body)
    4. Heuristic concerns/observations (fallback when no provider review)

    When provider review is present and has items, heuristic concern and
    observation sections are suppressed.  This avoids stacked competing
    review voices and makes the provider the single main review surface.

    Args:
        result: The structured scan result to format.
        concerns: Plan-informed review concerns.  Suppressed in markdown
            when provider review is present (kept internally as support).
        observations: Per-file review observations.  Suppressed in
            markdown when provider review is present (kept internally).
        provider_notes: Legacy provider candidate notes.  Suppressed
            whenever structured provider review is present.
        provider_review: Structured provider review output (ADR-044).
            When present, this becomes the primary review section.
        change_summary_bullets: Short factual change summary bullets
            (ADR-047).  Rendered near the top of the review to help
            orient the reader before detailed review content.

    Returns:
        A markdown string suitable for a GitHub PR comment.
    """
    lines: list[str] = []

    # -- Header --
    lines.append("## 🔒 parity-zero Security Review")
    lines.append("")

    # -- Decision & risk score --
    badge = _DECISION_BADGES.get(result.decision, result.decision.value)
    lines.append(f"**Decision:** {badge} · **Risk:** {_risk_bar(result.risk_score)}")
    lines.append("")

    # -- Change summary (ADR-047) --
    _append_change_summary(lines, change_summary_bullets)

    counts = result.summary_counts
    total = sum(counts.values())

    # ADR-045: When provider review is present and has items, it becomes
    # the primary review surface.  Heuristic concerns/observations are
    # suppressed to avoid stacked competing review voices.
    _has_provider_review = bool(provider_review and provider_review.has_items)

    if total == 0:
        lines.append("No security findings identified in this change.")
        lines.append("")
        _append_provider_review(lines, provider_review)
        if not _has_provider_review:
            _append_concerns(lines, concerns)
            _append_observations(lines, observations)
        _append_provider_notes(lines, provider_notes, provider_review)
        _append_footer(lines, result)
        return "\n".join(lines)

    lines.append(
        f"**{total} finding(s):** "
        f"🔴 {counts['high']} high · 🟡 {counts['medium']} medium · 🔵 {counts['low']} low"
    )
    lines.append("")

    # -- Findings grouped by severity --
    for severity in [Severity.HIGH, Severity.MEDIUM, Severity.LOW]:
        severity_findings = [f for f in result.findings if f.severity == severity]
        if not severity_findings:
            continue

        label = severity.value.upper()
        lines.append(f"### {label}")
        lines.append("")

        for finding in severity_findings:
            location = finding.file
            if finding.start_line:
                location += f":{finding.start_line}"
                if finding.end_line and finding.end_line != finding.start_line:
                    location += f"-{finding.end_line}"

            lines.append(f"- **{finding.title}** (`{finding.category.value}`) — `{location}`")
            lines.append(f"  {finding.description}")
            if finding.recommendation:
                lines.append(f"  > 💡 {finding.recommendation}")
            lines.append("")

    _append_provider_review(lines, provider_review)
    if not _has_provider_review:
        _append_concerns(lines, concerns)
        _append_observations(lines, observations)
    _append_provider_notes(lines, provider_notes, provider_review)
    _append_footer(lines, result)
    return "\n".join(lines)


def _append_change_summary(
    lines: list[str],
    bullets: list[str] | None,
) -> None:
    """Append a short deterministic change summary section (ADR-047).

    The summary is factual, not judgmental — it describes what changed,
    not what is risky or what needs attention.  That remains the provider
    review's job.
    """
    if not bullets:
        return

    lines.append("### 📝 What Changed")
    lines.append("")
    for bullet in bullets:
        lines.append(f"- {bullet}")
    lines.append("")


def _append_provider_review(
    lines: list[str],
    provider_review: ProviderReview | None,
) -> None:
    """Append structured provider review items as the primary review section.

    Provider review items are the primary non-authoritative review surface
    (ADR-044, ADR-045).  When present, this section is the main
    explanatory/review layer — heuristic concerns and observations are
    suppressed in favour of this provider-led content.

    Items are clearly marked as non-authoritative candidate material.
    """
    if not provider_review or not provider_review.has_items:
        return

    # Show up to 8 items — the full validated set.
    shown = provider_review.items[:8]

    lines.append("### 🤖 Provider Security Review")
    lines.append("")
    lines.append(
        "*Security review by the reasoning provider — these are "
        "evidence-based observations on the changed code.  They are "
        "not proven findings and do not affect the decision or risk score.*"
    )
    lines.append("")

    _KIND_ICONS = {
        "candidate_finding": "🔎",
        "candidate_observation": "👁️",
        "review_attention": "⚡",
    }

    for item in shown:
        icon = _KIND_ICONS.get(item.kind, "📝")
        confidence_tag = f"confidence: {item.confidence}"
        category_tag = f", `{item.category}`" if item.category else ""
        lines.append(
            f"- {icon} **{item.title}** ({confidence_tag}{category_tag})"
        )
        lines.append(f"  {item.summary}")
        if item.evidence:
            evidence_short = item.evidence[:200]
            if len(item.evidence) > 200:
                evidence_short = evidence_short.rsplit(" ", 1)[0] + "…"
            lines.append(f"  > Evidence: {evidence_short}")
        if item.paths:
            paths_str = ", ".join(f"`{p}`" for p in item.paths[:3])
            lines.append(f"  Files: {paths_str}")
        lines.append("")


def _append_concerns(
    lines: list[str],
    concerns: list[ReviewConcern] | None,
) -> None:
    """Append plan-informed review concerns as a clearly separated section.

    Concerns are contextual observations — not proven findings.  The section
    header and item formatting make this distinction explicit.

    When multiple concerns target the same paths, only the highest-confidence
    concerns are shown to avoid redundant messaging.
    """
    if not concerns:
        return

    # Deduplicate concerns that share the same paths — keep highest confidence.
    shown = _deduplicate_concerns(concerns, max_per_path=2, max_total=5)
    if not shown:
        return

    lines.append("### 🔍 Review Concerns")
    lines.append("")
    lines.append(
        "*The following are contextual observations — areas that may "
        "deserve closer attention based on repository context and review "
        "history. They are not proven findings.*"
    )
    lines.append("")

    for concern in shown:
        confidence_tag = f"confidence: {concern.confidence}"
        lines.append(
            f"- **{concern.title}** (`{concern.category}`, {confidence_tag})"
        )
        lines.append(f"  {concern.summary}")
        if concern.related_paths:
            paths_str = ", ".join(f"`{p}`" for p in concern.related_paths[:3])
            lines.append(f"  Related: {paths_str}")
        lines.append("")


# Confidence ordering for concern deduplication (higher = more useful).
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def _deduplicate_concerns(
    concerns: list[ReviewConcern],
    max_per_path: int = 2,
    max_total: int = 5,
) -> list[ReviewConcern]:
    """Reduce concern redundancy when many concerns target the same files.

    Keeps at most ``max_per_path`` concerns per unique path set, preferring
    higher confidence concerns.  Caps total at ``max_total``.
    """
    # Group by frozenset of related_paths (or title if no paths).
    groups: dict[str, list[ReviewConcern]] = {}
    for c in concerns:
        key = ",".join(sorted(c.related_paths)) if c.related_paths else c.title
        groups.setdefault(key, []).append(c)

    # Sort within each group by confidence rank (descending).
    result: list[ReviewConcern] = []
    for group in groups.values():
        sorted_group = sorted(
            group,
            key=lambda c: _CONFIDENCE_RANK.get(c.confidence, 0),
            reverse=True,
        )
        result.extend(sorted_group[:max_per_path])

    # Preserve original ordering (stable sort by position in original list).
    original_order = {id(c): i for i, c in enumerate(concerns)}
    result.sort(key=lambda c: original_order.get(id(c), 0))

    return result[:max_total]


def _append_observations(
    lines: list[str],
    observations: list[ReviewObservation] | None,
) -> None:
    """Append per-file review observations as a clearly separated section.

    Observations are targeted analysis notes tied to specific files.  They are
    distinct from findings (proven issues) and concerns (plan-level signals).
    """
    if not observations:
        return

    lines.append("### 📋 Review Observations")
    lines.append("")
    lines.append(
        "*Per-file analysis notes — these highlight why specific files "
        "may warrant closer review based on repository context.  "
        "They are not findings or proven issues.*"
    )
    lines.append("")

    for obs in observations:
        confidence_tag = f"confidence: {obs.confidence}"
        path_tag = f"`{obs.path}`" if obs.path else ""
        lines.append(
            f"- **{obs.title}** ({confidence_tag})"
            + (f" — {path_tag}" if path_tag else "")
        )
        lines.append(f"  {obs.summary}")
        if obs.related_paths:
            paths_str = ", ".join(f"`{p}`" for p in obs.related_paths[:3])
            lines.append(f"  Related: {paths_str}")
        lines.append("")


def _append_provider_notes(
    lines: list[str],
    notes: list[CandidateNote] | None,
    provider_review: ProviderReview | None = None,
) -> None:
    """Append provider candidate notes as a clearly separated section.

    Provider notes are additional security observations from the reasoning
    provider, shown only when they are distinct from existing concerns and
    observations.  They are explicitly non-authoritative.

    When structured provider review items (ADR-044) are present and non-empty,
    the legacy provider notes section is suppressed to avoid redundancy.

    Display is capped at 3 notes to keep the output concise.
    """
    # When structured provider review is present, skip legacy notes.
    if provider_review and provider_review.has_items:
        return

    if not notes:
        return

    useful_notes = list(notes)[:_MAX_DISPLAYED_NOTES]

    if not useful_notes:
        return

    lines.append("### 💬 Additional Review Notes")
    lines.append("")
    lines.append(
        "*AI-generated candidate observations — these are supplementary "
        "notes from the reasoning provider.  They are not proven findings "
        "and may require verification.*"
    )
    lines.append("")

    for note in useful_notes:
        confidence_tag = f"confidence: {note.confidence}"
        title = note.title or note.summary[:60]
        lines.append(f"- **{title}** ({confidence_tag})")
        if note.summary and note.summary != title:
            lines.append(f"  {note.summary}")
        if note.related_paths:
            paths_str = ", ".join(f"`{p}`" for p in note.related_paths[:3])
            lines.append(f"  Related: {paths_str}")
        lines.append("")


# Maximum provider notes displayed in markdown output.
_MAX_DISPLAYED_NOTES = 3


def _append_footer(lines: list[str], result: ScanResult) -> None:
    """Append a compact metadata footer."""
    lines.append("---")
    lines.append(
        f"*Scan: `{result.scan_id[:12]}` · "
        f"Commit: `{result.commit_sha[:7]}` · "
        f"Decision: {result.decision.value} · "
        f"Risk: {result.risk_score}*"
    )
    lines.append("")
