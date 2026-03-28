"""Narrow deterministic guardrails for parity-zero.

This module is limited to high-confidence checks that support the reviewer
without turning parity-zero into another SAST tool.  See ADR-004 and
architecture.md § Deterministic Checks.

Phase 1 implements:

  Insecure-configuration patterns (ADR-004):
    - CORS wildcard allowing all origins
    - debug mode enabled in production-like config
    - dangerous disablement of security checks (SSL verification, CSRF)

  Secrets detection (ADR-010):
    - AWS access key IDs (AKIA prefix)
    - private key headers (PEM format)
    - GitHub personal access tokens (ghp_/ghs_ prefix)

Any future checks should stay narrow, high-signal, and secondary to the
LLM reviewer.

Known limitations of secrets detection:
  - Only covers AWS key IDs, PEM private keys, and GitHub tokens.
  - Does not detect encoded, obfuscated, or multi-line secrets.
  - Does not support path-based suppression (e.g. test fixtures).
  - Does not detect secrets from other providers (GCP, Azure, etc.).
  - Later iterations may need suppression annotations, path-awareness,
    or integration with dedicated secret scanning tools.
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

# -- Secrets patterns (ADR-010) --
# These are intentionally narrow and high-confidence.  Each pattern targets
# a distinctive, well-known secret format that is unlikely to produce false
# positives in normal application code.

_SECRETS_PATTERNS: list[tuple[re.Pattern[str], str, str, str]] = [
    # (compiled regex, title, description, recommendation)
    (
        re.compile(r"""AKIA[0-9A-Z]{16}"""),
        "Hardcoded AWS access key ID",
        "An AWS access key ID (AKIA prefix) appears to be hardcoded in "
        "source code. Exposed AWS credentials can lead to unauthorised "
        "access to cloud resources.",
        "Remove the hardcoded key and use environment variables, a secrets "
        "manager, or IAM roles instead.",
    ),
    (
        re.compile(r"""-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"""),
        "Private key committed to source",
        "A PEM-encoded private key header was found in source code. "
        "Committed private keys can be extracted from repository history "
        "and used for unauthorised access.",
        "Remove the private key from source control, rotate it, and load "
        "keys from a secure secret store at runtime.",
    ),
    (
        re.compile(r"""gh[ps]_[A-Za-z0-9]{36}"""),
        "Hardcoded GitHub token",
        "A GitHub personal access token or GitHub App installation token "
        "appears to be hardcoded. Exposed tokens can grant access to "
        "repositories, APIs, and organisation resources.",
        "Remove the token from source code, revoke it, and use GitHub "
        "Actions secrets or a credential manager instead.",
    ),
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


def _check_secrets(filepath: str, content: str) -> list[Finding]:
    """Detect obvious hardcoded secrets in source code.

    Targets a small set of high-confidence patterns: AWS access key IDs,
    PEM private key headers, and GitHub tokens.  See module docstring for
    known limitations.
    """
    findings: list[Finding] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern, title, description, recommendation in _SECRETS_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    category=Category.SECRETS,
                    severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    title=title,
                    description=description,
                    file=filepath,
                    start_line=line_num,
                    recommendation=recommendation,
                ))
                break  # one finding per line is sufficient
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
        findings.extend(_check_secrets(filepath, content))

    return findings
