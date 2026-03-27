"""Markdown summary formatter for parity-zero PR output.

Converts a ScanResult into a developer-friendly markdown summary suitable
for posting as a GitHub PR comment.

Design goals (from team.md):
  - clear, practical, and low-noise
  - actionable recommendations
  - minimal workflow disruption

The markdown output is a *presentation* layer.  The structured JSON
ScanResult remains the authoritative system contract.
"""

from __future__ import annotations

from schemas.findings import ScanResult, Severity


def format_markdown(result: ScanResult) -> str:
    """Render a ScanResult as a markdown PR summary.

    Args:
        result: The structured scan result to format.

    Returns:
        A markdown string suitable for a GitHub PR comment.
    """
    lines: list[str] = []

    lines.append("## 🔒 parity-zero Security Review")
    lines.append("")

    counts = result.summary_counts
    total = sum(counts.values())

    if total == 0:
        lines.append("No security findings identified in this change.")
        lines.append("")
        lines.append("---")
        lines.append(f"*Scan: `{result.scan_id[:12]}` · Commit: `{result.commit_sha[:7]}`*")
        lines.append("")
        return "\n".join(lines)

    lines.append(
        f"**{total} finding(s):** "
        f"🔴 {counts['high']} high · 🟡 {counts['medium']} medium · 🔵 {counts['low']} low"
    )
    lines.append("")

    # Group by severity for readability.
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

    lines.append("---")
    lines.append(f"*Scan: `{result.scan_id[:12]}` · Commit: `{result.commit_sha[:7]}`*")
    lines.append("")

    return "\n".join(lines)
