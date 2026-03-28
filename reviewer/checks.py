"""Narrow deterministic guardrails for parity-zero.

This module is limited to high-confidence checks that support the reviewer
without turning parity-zero into another SAST tool.  See ADR-004 and
architecture.md § Deterministic Checks.

Phase 1 implements a small set of insecure-configuration patterns:
  - CORS wildcard allowing all origins
  - debug mode enabled in production-like config
  - dangerous disablement of security checks (SSL verification, CSRF)

Any future checks should stay narrow, high-signal, and secondary to the
LLM reviewer.
"""

from __future__ import annotations

import re

from schemas.findings import Category, Confidence, Finding, Severity

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------
# Each pattern is a tuple of (compiled regex, title, description,
# recommendation, severity, confidence).  Patterns are applied per-line
# against file contents.

_CORS_WILDCARD_PATTERNS = [
    re.compile(r"""allow_origins\s*=\s*\[["']\*["']\]"""),
    re.compile(r"""CORS_ALLOW_ALL\s*=\s*True"""),
    re.compile(r"""CORS_ORIGIN_ALLOW_ALL\s*=\s*True"""),
    re.compile(r"""Access-Control-Allow-Origin.*\*"""),
]

_DEBUG_MODE_PATTERNS = [
    re.compile(r"""(?<!\w)DEBUG\s*=\s*True(?!\w)"""),
    re.compile(r"""(?<!\w)debug\s*=\s*True(?!\w)"""),
    re.compile(r"""(?<!\w)debug\s*:\s*true(?!\w)""", re.IGNORECASE),
]

_SECURITY_DISABLEMENT_PATTERNS = [
    (re.compile(r"""VERIFY_SSL\s*=\s*False"""), "SSL verification disabled"),
    (re.compile(r"""verify_ssl\s*=\s*False"""), "SSL verification disabled"),
    (re.compile(r"""verify\s*=\s*False"""), "SSL verification disabled"),
    (re.compile(r"""CSRF_ENABLED\s*=\s*False"""), "CSRF protection disabled"),
    (re.compile(r"""csrf_enabled\s*=\s*False"""), "CSRF protection disabled"),
    (re.compile(r"""WTF_CSRF_ENABLED\s*=\s*False"""), "CSRF protection disabled"),
]


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def _check_cors_wildcard(filepath: str, content: str) -> list[Finding]:
    """Detect obviously permissive CORS wildcard configuration."""
    findings: list[Finding] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern in _CORS_WILDCARD_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    category=Category.INSECURE_CONFIGURATION,
                    severity=Severity.MEDIUM,
                    confidence=Confidence.HIGH,
                    title="CORS wildcard allows all origins",
                    description=(
                        "The configuration allows requests from any origin. "
                        "This can expose the application to cross-origin attacks."
                    ),
                    file=filepath,
                    start_line=line_num,
                    recommendation=(
                        "Restrict CORS origins to a specific allowlist "
                        "of trusted domains."
                    ),
                ))
                break  # one finding per line is sufficient
    return findings


def _check_debug_mode(filepath: str, content: str) -> list[Finding]:
    """Detect debug mode enabled in configuration files."""
    findings: list[Finding] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern in _DEBUG_MODE_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    category=Category.INSECURE_CONFIGURATION,
                    severity=Severity.LOW,
                    confidence=Confidence.HIGH,
                    title="Debug mode enabled",
                    description=(
                        "Debug mode is enabled in what appears to be "
                        "application configuration. Debug mode often exposes "
                        "stack traces, internal state, and verbose error "
                        "messages to end users."
                    ),
                    file=filepath,
                    start_line=line_num,
                    recommendation=(
                        "Disable debug mode in production configurations. "
                        "Use environment-specific settings to keep debug "
                        "mode off by default."
                    ),
                ))
                break
    return findings


def _check_security_disablement(filepath: str, content: str) -> list[Finding]:
    """Detect dangerous disablement of security checks."""
    findings: list[Finding] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern, label in _SECURITY_DISABLEMENT_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    category=Category.INSECURE_CONFIGURATION,
                    severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    title=label,
                    description=(
                        f"A security mechanism is explicitly disabled: "
                        f"{label.lower()}. This removes an important "
                        f"protection layer."
                    ),
                    file=filepath,
                    start_line=line_num,
                    recommendation=(
                        "Re-enable the security mechanism. If disablement "
                        "is required for local development, ensure it is "
                        "controlled by an environment variable and never "
                        "disabled in production."
                    ),
                ))
                break
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_deterministic_checks(file_contents: dict[str, str]) -> list[Finding]:
    """Run the narrow deterministic guardrails against changed file contents.

    Args:
        file_contents: Mapping of repo-relative file paths to their text
            content.

    Returns:
        Findings from supplemental deterministic analysis.
    """
    findings: list[Finding] = []

    for filepath, content in file_contents.items():
        findings.extend(_check_cors_wildcard(filepath, content))
        findings.extend(_check_debug_mode(filepath, content))
        findings.extend(_check_security_disablement(filepath, content))

    return findings
