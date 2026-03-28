"""Markdown summary formatter for parity-zero PR output.

Converts a ScanResult into a developer-friendly markdown summary suitable
for posting as a GitHub PR comment.

Optionally includes plan-informed review concerns (ADR-022) — contextual
observations that are clearly distinct from proven findings.

Optionally includes per-file review observations (ADR-024) — targeted
analysis of why specific files deserve scrutiny, derived from ReviewBundle
evidence.

Optionally includes provider candidate notes (ADR-027) — additional
security-relevant observations from the reasoning provider, shown only
when distinct from existing concerns and observations.

Design goals (from team.md):
  - clear, practical, and low-noise
  - actionable recommendations
  - minimal workflow disruption

The markdown output is a *presentation* layer.  The structured JSON
ScanResult remains the authoritative system contract.
"""

from __future__ import annotations

from reviewer.models import ReviewConcern, ReviewObservation
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
) -> str:
    """Render a ScanResult as a markdown PR summary.

    Args:
        result: The structured scan result to format.
        concerns: Optional plan-informed review concerns to display
            in a separate section.  These are clearly distinct from
            proven findings.
        observations: Optional per-file review observations to display
            in a separate section.  These are targeted analysis notes
            tied to specific files, distinct from both findings and
            concerns.
        provider_notes: Optional normalized candidate notes from the
            reasoning provider, shown in a distinct section when they
            add value beyond concerns and observations.

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

    counts = result.summary_counts
    total = sum(counts.values())

    if total == 0:
        lines.append("No security findings identified in this change.")
        lines.append("")
        _append_concerns(lines, concerns)
        _append_observations(lines, observations)
        _append_provider_notes(lines, provider_notes)
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

    # -- Actionable recommendations --
    recommendations = [
        (f.title, f.recommendation)
        for f in result.findings
        if f.recommendation
    ]
    if recommendations:
        lines.append("### Recommendations")
        lines.append("")
        for title, rec in recommendations:
            lines.append(f"- **{title}:** {rec}")
        lines.append("")

    _append_concerns(lines, concerns)
    _append_observations(lines, observations)
    _append_provider_notes(lines, provider_notes)
    _append_footer(lines, result)
    return "\n".join(lines)


def _append_concerns(
    lines: list[str],
    concerns: list[ReviewConcern] | None,
) -> None:
    """Append plan-informed review concerns as a clearly separated section.

    Concerns are contextual observations — not proven findings.  The section
    header and item formatting make this distinction explicit.
    """
    if not concerns:
        return

    lines.append("### 🔍 Review Concerns")
    lines.append("")
    lines.append(
        "*The following are contextual observations — areas that may "
        "deserve closer attention based on repository context and review "
        "history. They are not proven findings.*"
    )
    lines.append("")

    for concern in concerns:
        confidence_tag = f"confidence: {concern.confidence}"
        lines.append(
            f"- **{concern.title}** (`{concern.category}`, {confidence_tag})"
        )
        lines.append(f"  {concern.summary}")
        if concern.related_paths:
            paths_str = ", ".join(f"`{p}`" for p in concern.related_paths[:3])
            lines.append(f"  Related: {paths_str}")
        lines.append("")


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
) -> None:
    """Append provider candidate notes as a clearly separated section.

    Provider notes are additional security observations from the reasoning
    provider, shown only when they are distinct from existing concerns and
    observations.  They are explicitly non-authoritative.
    """
    if not notes:
        return

    lines.append("### 💬 Additional Review Notes")
    lines.append("")
    lines.append(
        "*AI-generated candidate observations — these are supplementary "
        "notes from the reasoning provider.  They are not proven findings "
        "and may require verification.*"
    )
    lines.append("")

    for note in notes[:5]:
        confidence_tag = f"confidence: {note.confidence}"
        title = note.title or note.summary[:60]
        lines.append(f"- **{title}** ({confidence_tag})")
        if note.summary and note.summary != title:
            lines.append(f"  {note.summary}")
        if note.related_paths:
            paths_str = ", ".join(f"`{p}`" for p in note.related_paths[:3])
            lines.append(f"  Related: {paths_str}")
        lines.append("")


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
