"""Scenario format and curated corpus for PR validation (ADR-032).

A ``ValidationScenario`` pairs a synthetic PR situation with expected
reviewer behavior.  The format is intentionally simple:

- **changed_files** — required dict of ``{path: content}``
- **baseline_profile** — optional ``RepoSecurityProfile``
- **memory** — optional ``ReviewMemory``
- **provider_mode** — ``"disabled"`` (default) or ``"mock"``
- **expected** — ``ExpectedBehavior`` describing what the reviewer
  should (or should not) produce

The curated corpus (``SCENARIOS``) covers representative paths through
the reviewer pipeline — from trivial no-signal PRs to auth-sensitive
changes to provider-enriched observations.

This is deliberately *not* a full benchmark schema.  See deferred
concerns in ADR-032.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from reviewer.models import (
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)


# ------------------------------------------------------------------
# Expected behavior specification
# ------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedBehavior:
    """Declarative expectation for a scenario's reviewer output.

    Each field is optional — only specified expectations are validated.
    ``None`` means "no assertion for this aspect".

    Attributes:
        provider_gate_invoked: Whether provider gating should invoke.
            ``True`` means invoke expected, ``False`` means skip expected,
            ``None`` means don't check.
        min_findings: Minimum expected findings count.
        max_findings: Maximum expected findings count.
        finding_categories_present: Finding categories that must appear.
        finding_categories_absent: Finding categories that must not appear.
        has_concerns: Whether concerns should be present.
        has_observations: Whether observations should be present.
        markdown_contains: Substrings the markdown output must contain.
        markdown_omits: Substrings the markdown output must not contain.
        no_trust_boundary_violations: Assert that provider output did
            not pollute scoring/decision/findings.  Default ``True``.
    """

    provider_gate_invoked: bool | None = None
    min_findings: int | None = None
    max_findings: int | None = None
    finding_categories_present: list[str] = field(default_factory=list)
    finding_categories_absent: list[str] = field(default_factory=list)
    has_concerns: bool | None = None
    has_observations: bool | None = None
    markdown_contains: list[str] = field(default_factory=list)
    markdown_omits: list[str] = field(default_factory=list)
    no_trust_boundary_violations: bool = True


# ------------------------------------------------------------------
# Scenario format
# ------------------------------------------------------------------


@dataclass
class ValidationScenario:
    """A curated PR scenario with expected reviewer behavior.

    Attributes:
        id: Unique short identifier (e.g. ``"auth-sensitive"``).
        description: Human-readable description of the scenario intent.
        changed_files: Synthetic file contents ``{path: content}``.
        baseline_profile: Optional repo-level security context.
        memory: Optional review memory context.
        provider_mode: ``"disabled"`` or ``"mock"`` — never live.
        expected: Expected reviewer behavior for validation.
    """

    id: str
    description: str
    changed_files: dict[str, str]
    expected: ExpectedBehavior
    baseline_profile: RepoSecurityProfile | None = None
    memory: ReviewMemory | None = None
    provider_mode: Literal["disabled", "mock"] = "disabled"


# ------------------------------------------------------------------
# Curated scenario corpus
# ------------------------------------------------------------------


def _auth_sensitive_scenario() -> ValidationScenario:
    """Auth-sensitive PR touching login and session management."""
    return ValidationScenario(
        id="auth-sensitive",
        description=(
            "PR modifies authentication-related files in a repo with "
            "known auth patterns.  Should trigger provider gate and "
            "produce auth-related concerns/observations.  Includes a "
            "hardcoded AWS key for deterministic secrets detection."
        ),
        changed_files={
            "src/auth/login.py": (
                "from flask import request, session\n"
                "\n"
                "def login():\n"
                "    username = request.form['username']\n"
                "    password = request.form['password']\n"
                "    # TODO: add rate limiting\n"
                "    if check_password(username, password):\n"
                "        session['user'] = username\n"
                "        return redirect('/dashboard')\n"
            ),
            "src/auth/session.py": (
                "import jwt\n"
                "\n"
                "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
                "\n"
                "def create_token(user_id):\n"
                "    return jwt.encode({'sub': user_id}, AWS_KEY)\n"
            ),
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/auth/", "config/"],
            auth_patterns=["jwt", "session"],
        ),
        provider_mode="mock",
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            min_findings=1,
            finding_categories_present=["secrets"],
            has_concerns=True,
            has_observations=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


def _sensitive_config_scenario() -> ValidationScenario:
    """Config PR with debug mode and CORS wildcard."""
    return ValidationScenario(
        id="sensitive-config",
        description=(
            "PR enables debug mode and sets a CORS wildcard in config. "
            "Should produce insecure_configuration findings deterministically."
        ),
        changed_files={
            "config/settings.py": (
                "DEBUG = True\n"
                "ALLOWED_HOSTS = ['*']\n"
                "CORS_ORIGIN_ALLOW_ALL = True\n"
            ),
            "config/cors.py": (
                "from flask_cors import CORS\n"
                "\n"
                "def init_cors(app):\n"
                '    CORS(app, origins="*")\n'
            ),
        },
        expected=ExpectedBehavior(
            min_findings=2,
            finding_categories_present=["insecure_configuration"],
            markdown_contains=["Security Review", "insecure_configuration"],
            no_trust_boundary_violations=True,
        ),
    )


def _trivial_docs_scenario() -> ValidationScenario:
    """Trivial docs/readme PR — should NOT invoke provider."""
    return ValidationScenario(
        id="trivial-docs",
        description=(
            "PR only changes documentation and readme files.  No security "
            "signals.  Should not invoke provider, produce no findings, "
            "and result in a clean pass."
        ),
        changed_files={
            "README.md": (
                "# My Project\n\n"
                "Updated installation instructions.\n"
            ),
            "docs/contributing.md": (
                "# Contributing\n\n"
                "Please follow the coding guidelines.\n"
            ),
        },
        expected=ExpectedBehavior(
            provider_gate_invoked=False,
            max_findings=0,
            finding_categories_absent=[
                "authentication",
                "authorization",
                "secrets",
            ],
            has_concerns=False,
            markdown_contains=["No security findings"],
            markdown_omits=["HIGH", "MEDIUM"],
            no_trust_boundary_violations=True,
        ),
    )


def _memory_influenced_scenario() -> ValidationScenario:
    """PR in a repo with relevant review memory."""
    return ValidationScenario(
        id="memory-influenced",
        description=(
            "PR changes auth-related routes in a repo where review memory "
            "records prior authentication and input_validation issues.  "
            "Memory should influence planning and gate invocation."
        ),
        changed_files={
            "src/auth/routes.py": (
                "from flask import request, jsonify\n"
                "\n"
                "def get_user(user_id):\n"
                "    # fetch user from database\n"
                "    return jsonify(db.get_user(user_id))\n"
                "\n"
                "def update_user(user_id):\n"
                "    data = request.get_json()\n"
                "    db.update_user(user_id, data)\n"
                "    return jsonify({'status': 'ok'})\n"
            ),
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/auth/"],
            auth_patterns=["jwt"],
        ),
        memory=ReviewMemory(
            repo="acme/webapp",
            entries=[
                ReviewMemoryEntry(
                    category="authentication",
                    summary="Prior PR had missing auth checks on API routes",
                    repo="acme/webapp",
                ),
                ReviewMemoryEntry(
                    category="input_validation",
                    summary="Previous review found unvalidated JSON payloads",
                    repo="acme/webapp",
                ),
            ],
        ),
        provider_mode="mock",
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            has_concerns=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


def _deterministic_only_scenario() -> ValidationScenario:
    """PR with hardcoded secrets — detected purely by deterministic checks."""
    return ValidationScenario(
        id="deterministic-only",
        description=(
            "PR contains a hardcoded AWS key.  Should be detected by "
            "deterministic checks alone (no provider needed).  Provider "
            "is disabled."
        ),
        changed_files={
            "deploy/credentials.py": (
                "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n"
                "AWS_SECRET_ACCESS_KEY = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'\n"
            ),
        },
        provider_mode="disabled",
        expected=ExpectedBehavior(
            provider_gate_invoked=None,  # don't check — provider disabled
            min_findings=1,
            finding_categories_present=["secrets"],
            markdown_contains=["Security Review", "secrets"],
            no_trust_boundary_violations=True,
        ),
    )


def _provider_enriched_scenario() -> ValidationScenario:
    """PR where mock provider enriches observations."""
    return ValidationScenario(
        id="provider-enriched",
        description=(
            "Auth-sensitive PR with mock provider enabled.  Observations "
            "should be present and provider notes should appear in output. "
            "Provider output must not affect scoring."
        ),
        changed_files={
            "src/auth/middleware.py": (
                "from functools import wraps\n"
                "from flask import request, abort\n"
                "\n"
                "def require_auth(f):\n"
                "    @wraps(f)\n"
                "    def decorated(*args, **kwargs):\n"
                "        token = request.headers.get('Authorization')\n"
                "        if not token:\n"
                "            abort(401)\n"
                "        return f(*args, **kwargs)\n"
                "    return decorated\n"
            ),
            "src/api/admin.py": (
                "from src.auth.middleware import require_auth\n"
                "\n"
                "@require_auth\n"
                "def admin_panel():\n"
                "    return render_admin_page()\n"
            ),
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/auth/", "src/api/"],
            auth_patterns=["jwt", "session", "token"],
        ),
        provider_mode="mock",
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            has_observations=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


def _low_noise_test_scenario() -> ValidationScenario:
    """Test-file-only PR — should be quiet and clean."""
    return ValidationScenario(
        id="low-noise-tests",
        description=(
            "PR only changes test files.  Should produce minimal or no "
            "findings, no concerns, and a clean review."
        ),
        changed_files={
            "tests/test_utils.py": (
                "import pytest\n"
                "\n"
                "def test_add():\n"
                "    assert 1 + 1 == 2\n"
                "\n"
                "def test_subtract():\n"
                "    assert 2 - 1 == 1\n"
            ),
            "tests/test_helpers.py": (
                "def test_format_name():\n"
                "    assert format_name('john', 'doe') == 'John Doe'\n"
            ),
        },
        expected=ExpectedBehavior(
            provider_gate_invoked=False,
            max_findings=0,
            has_concerns=False,
            markdown_contains=["No security findings"],
            no_trust_boundary_violations=True,
        ),
    )


# ------------------------------------------------------------------
# Corpus registry
# ------------------------------------------------------------------

SCENARIOS: list[ValidationScenario] = [
    _auth_sensitive_scenario(),
    _sensitive_config_scenario(),
    _trivial_docs_scenario(),
    _memory_influenced_scenario(),
    _deterministic_only_scenario(),
    _provider_enriched_scenario(),
    _low_noise_test_scenario(),
]


def get_scenario(scenario_id: str) -> ValidationScenario | None:
    """Look up a scenario by its unique id.

    Returns:
        The matching scenario, or ``None`` if not found.
    """
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    return None


def list_scenario_ids() -> list[str]:
    """Return the ids of all registered scenarios."""
    return [s.id for s in SCENARIOS]
