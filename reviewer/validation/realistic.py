"""Realistic evaluation corpus with file-backed fixtures (ADR-039).

This module defines a corpus of realistic PR-like fixtures that are
more representative than the minimal synthetic scenarios in the base
validation harness.  Each scenario loads fixture content from files in
``test/eval/fixtures/`` and pairs it with phase-appropriate expectations.

The realistic corpus is designed to help answer:

- How does parity-zero behave on more realistic PR-shaped fixtures?
- Which provider mode adds value and where?
- Where is the reviewer noisy, shallow, or redundant?
- Are trust boundaries still holding under realistic scenarios?

Realistic scenarios use the same ``ValidationScenario`` format as the
base harness so they plug into the existing runner, comparison, and
assertion infrastructure.  They are registered with a ``realistic`` tag
for easy filtering.

This is intentionally **not** a benchmark framework.  See ADR-039 for
scope and deferred concerns.
"""

from __future__ import annotations

import os
from pathlib import Path

from reviewer.models import (
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)
from reviewer.validation.scenario import (
    ExpectedBehavior,
    ValidationScenario,
)


# ------------------------------------------------------------------
# Fixture loading
# ------------------------------------------------------------------

_FIXTURE_DIR = Path(__file__).resolve().parent.parent.parent / "test" / "eval" / "fixtures"


def _load_fixture(scenario_dir: str, filename: str) -> str:
    """Load a fixture file's content as a string.

    Args:
        scenario_dir: Subdirectory name under ``test/eval/fixtures/``.
        filename: File name within the scenario directory.

    Returns:
        The file content as a UTF-8 string.

    Raises:
        FileNotFoundError: If the fixture file does not exist.
    """
    path = _FIXTURE_DIR / scenario_dir / filename
    return path.read_text(encoding="utf-8")


def _load_fixture_dir(scenario_dir: str, *, path_prefix: str = "") -> dict[str, str]:
    """Load all files from a fixture directory as ``{path: content}``.

    Args:
        scenario_dir: Subdirectory name under ``test/eval/fixtures/``.
        path_prefix: Optional prefix for simulated file paths.  If
            empty, filenames are used directly.

    Returns:
        Dict mapping simulated file paths to file content.
    """
    dir_path = _FIXTURE_DIR / scenario_dir
    files: dict[str, str] = {}
    for entry in sorted(dir_path.iterdir()):
        if entry.is_file() and not entry.name.startswith("."):
            if path_prefix:
                sim_path = f"{path_prefix}/{entry.name}"
            else:
                sim_path = entry.name
            files[sim_path] = entry.read_text(encoding="utf-8")
    return files


# ------------------------------------------------------------------
# Realistic scenario definitions
# ------------------------------------------------------------------


def _missing_auth_on_route() -> ValidationScenario:
    """New API routes handling user data without any auth decorator.

    A realistic Flask blueprint with CRUD endpoints that expose user
    data and allow modifications without authentication.  The reviewer
    should notice the sensitive operations and the absence of auth
    checks, ideally producing auth-related concerns/observations.
    """
    content = _load_fixture("missing_auth_on_route", "api_users.py")
    return ValidationScenario(
        id="realistic-missing-auth-route",
        description=(
            "New user management API routes with CRUD operations but no "
            "authentication decorators.  Sensitive user data exposed "
            "without access control.  Provider should add contextual "
            "observations about the missing auth pattern."
        ),
        changed_files={
            "src/auth/users.py": content,
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/auth/"],
            auth_patterns=["require_login", "require_auth", "jwt"],
        ),
        provider_mode="mock",
        tags=["realistic", "auth", "provider-value"],
        security_focus=["authentication"],
        provider_value_expected=True,
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            has_concerns=True,
            has_observations=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


def _authz_business_logic() -> ValidationScenario:
    """Invoice processing where any authenticated user can approve.

    A realistic authorization-sensitive scenario: the user is logged
    in but there is no role/ownership check for sensitive business
    operations.  This is subtle — deterministic checks will not catch
    it, but provider reasoning may add useful observations.
    """
    content = _load_fixture("authz_business_logic", "invoices.py")
    return ValidationScenario(
        id="realistic-authz-business-logic",
        description=(
            "Invoice approval and voiding endpoints where any authenticated "
            "user can approve any invoice — no role or ownership checks.  "
            "Subtle authorization gap that benefits from contextual review."
        ),
        changed_files={
            "src/admin/invoices.py": content,
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/admin/", "src/auth/"],
            auth_patterns=["require_login", "require_auth"],
        ),
        provider_mode="mock",
        tags=["realistic", "authz", "provider-value"],
        security_focus=["authorization"],
        provider_value_expected=True,
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            has_concerns=True,
            has_observations=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


def _unsafe_sql_input() -> ValidationScenario:
    """Search endpoints with SQL injection via string interpolation.

    A realistic input validation scenario with direct SQL string
    formatting from user input.  This is a classic vulnerability
    pattern.  Deterministic checks may not catch it (the reviewer
    does not yet have SQL injection detection), but provider
    reasoning should add useful observations.
    """
    content = _load_fixture("unsafe_sql_input", "search.py")
    return ValidationScenario(
        id="realistic-unsafe-sql-input",
        description=(
            "Product and user search endpoints that interpolate user input "
            "directly into SQL queries.  Classic SQL injection pattern.  "
            "Provider reasoning should add contextual observations."
        ),
        changed_files={
            "src/middleware/search.py": content,
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/middleware/"],
            auth_patterns=["session"],
        ),
        memory=ReviewMemory(
            repo="acme/webapp",
            entries=[
                ReviewMemoryEntry(
                    category="input_validation",
                    summary="Prior review flagged SQL injection risk in query endpoints",
                    repo="acme/webapp",
                ),
            ],
        ),
        provider_mode="mock",
        tags=["realistic", "input-validation", "memory", "provider-value"],
        security_focus=["input_validation"],
        provider_value_expected=True,
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            has_concerns=True,
            has_observations=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


def _insecure_session_config() -> ValidationScenario:
    """Application settings with debug mode and insecure session cookies.

    A realistic insecure configuration scenario: debug mode enabled,
    session cookies without secure/httponly flags, and overly
    permissive CORS.  Deterministic checks should catch the debug
    mode and CORS wildcard.
    """
    content = _load_fixture("insecure_session_config", "settings.py")
    return ValidationScenario(
        id="realistic-insecure-session-config",
        description=(
            "Application settings with DEBUG=True, session cookies "
            "without secure/httponly flags, CORS wildcard, and "
            "disabled security headers.  Deterministic checks "
            "should detect debug mode.  Other issues are subtle "
            "and may benefit from provider observations."
        ),
        changed_files={
            "config/settings.py": content,
        },
        tags=["realistic", "config", "deterministic"],
        security_focus=["insecure_configuration"],
        provider_value_expected=False,
        expected=ExpectedBehavior(
            min_findings=1,
            finding_categories_present=["insecure_configuration"],
            markdown_contains=["Security Review", "insecure_configuration"],
            no_trust_boundary_violations=True,
        ),
    )


def _github_token_in_env() -> ValidationScenario:
    """Deployment config with an embedded GitHub personal access token.

    A realistic secrets scenario: a ghp_ token committed in a config
    file.  Deterministic checks should catch this pattern.
    """
    content = _load_fixture("github_token_in_env", "deploy_config.py")
    return ValidationScenario(
        id="realistic-github-token-exposure",
        description=(
            "Deployment configuration file containing a GitHub personal "
            "access token (ghp_...).  Should be detected by deterministic "
            "secrets checks.  No provider reasoning needed."
        ),
        changed_files={
            "deploy/config.py": content,
        },
        provider_mode="disabled",
        tags=["realistic", "secrets", "deterministic", "no-provider"],
        security_focus=["secrets"],
        provider_value_expected=False,
        expected=ExpectedBehavior(
            min_findings=1,
            finding_categories_present=["secrets"],
            markdown_contains=["Security Review", "secrets"],
            no_trust_boundary_violations=True,
        ),
    )


def _harmless_utility_refactor() -> ValidationScenario:
    """Pure utility refactoring with no security implications.

    A realistic low-signal scenario: date and string utilities
    refactored for consistency.  The reviewer should stay quiet.
    """
    files = _load_fixture_dir("harmless_utility_refactor", path_prefix="src/utils")
    return ValidationScenario(
        id="realistic-harmless-refactor",
        description=(
            "Pure utility code refactoring — date and string helpers "
            "reorganized for consistency.  No security-relevant changes.  "
            "Reviewer should produce no findings and minimal output."
        ),
        changed_files=files,
        tags=["realistic", "low-signal", "no-findings", "gate-skip"],
        security_focus=[],
        provider_value_expected=False,
        expected=ExpectedBehavior(
            provider_gate_invoked=False,
            max_findings=0,
            has_concerns=False,
            max_concerns=0,
            max_observations=0,
            has_provider_notes=False,
            markdown_contains=["No security findings"],
            absent_sections=["Provider Notes"],
            no_trust_boundary_violations=True,
        ),
    )


def _docs_and_changelog() -> ValidationScenario:
    """Documentation and changelog update — no security signals.

    A realistic low-signal scenario: CONTRIBUTING.md and CHANGELOG.md
    updated.  The reviewer should stay completely quiet.
    """
    files = _load_fixture_dir("docs_and_changelog", path_prefix="docs")
    return ValidationScenario(
        id="realistic-docs-changelog",
        description=(
            "Updates to CONTRIBUTING.md and CHANGELOG.md.  No code changes, "
            "no security signals.  Reviewer should produce no findings."
        ),
        changed_files=files,
        tags=["realistic", "low-signal", "no-findings", "gate-skip"],
        security_focus=[],
        provider_value_expected=False,
        expected=ExpectedBehavior(
            provider_gate_invoked=False,
            max_findings=0,
            has_concerns=False,
            max_concerns=0,
            max_observations=0,
            has_provider_notes=False,
            markdown_contains=["No security findings"],
            absent_sections=["Provider Notes"],
            no_trust_boundary_violations=True,
        ),
    )


def _test_coverage_expansion() -> ValidationScenario:
    """Test files added — no production code, no security signals.

    A realistic low-signal scenario: new test files for existing
    utility modules.  Should produce no findings.
    """
    files = _load_fixture_dir("test_coverage_expansion", path_prefix="tests")
    return ValidationScenario(
        id="realistic-test-expansion",
        description=(
            "New test files for date and string utility modules.  No "
            "production code changes, no security signals.  Reviewer "
            "should produce no findings."
        ),
        changed_files=files,
        tags=["realistic", "low-signal", "no-findings", "gate-skip"],
        security_focus=[],
        provider_value_expected=False,
        expected=ExpectedBehavior(
            provider_gate_invoked=False,
            max_findings=0,
            has_concerns=False,
            max_concerns=0,
            max_observations=0,
            has_provider_notes=False,
            markdown_contains=["No security findings"],
            absent_sections=["Provider Notes"],
            no_trust_boundary_violations=True,
        ),
    )


def _provider_helpful_auth() -> ValidationScenario:
    """OAuth2 middleware where provider adds contextual value.

    A realistic provider-helpful scenario: complex auth middleware
    with token validation, session management, and scope checking.
    The code is well-structured but has areas where provider reasoning
    can add useful security observations (e.g., token binding,
    session revocation patterns).  No deterministic findings expected.
    """
    content = _load_fixture("provider_helpful_auth", "oauth_middleware.py")
    return ValidationScenario(
        id="realistic-provider-helpful-auth",
        description=(
            "Complex OAuth2 middleware with token validation, session "
            "management, and scope checking.  No deterministic findings "
            "expected, but provider reasoning should add contextual "
            "observations about auth patterns and session security."
        ),
        changed_files={
            "src/auth/oauth_middleware.py": content,
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/auth/", "src/api/"],
            auth_patterns=["jwt", "oauth", "session", "token"],
        ),
        provider_mode="mock",
        tags=["realistic", "auth", "provider-value", "observations"],
        security_focus=["authentication", "authorization"],
        provider_value_expected=True,
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            has_concerns=True,
            has_observations=True,
            has_provider_notes=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


def _memory_recurring_vuln() -> ValidationScenario:
    """API key rotation with review memory of prior authorization issues.

    A realistic memory-influenced scenario: code that manages API key
    creation and rotation where review memory records prior issues with
    missing ownership checks.  The provider should use memory context
    to add relevant observations.
    """
    content = _load_fixture("memory_recurring_vuln", "api_key_rotation.py")
    return ValidationScenario(
        id="realistic-memory-recurring-vuln",
        description=(
            "API key creation and rotation endpoints where any user can "
            "rotate any key.  Review memory records prior authorization "
            "issues with missing ownership checks.  Provider should use "
            "memory context to add relevant observations."
        ),
        changed_files={
            "src/auth/api_key_rotation.py": content,
        },
        baseline_profile=RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python"],
            frameworks=["flask"],
            sensitive_paths=["src/auth/"],
            auth_patterns=["require_login", "api_key"],
        ),
        memory=ReviewMemory(
            repo="acme/webapp",
            entries=[
                ReviewMemoryEntry(
                    category="authorization",
                    summary=(
                        "Prior review flagged missing ownership check on "
                        "API key rotation — any authenticated user could "
                        "rotate any key"
                    ),
                    repo="acme/webapp",
                ),
                ReviewMemoryEntry(
                    category="authentication",
                    summary="Previous review noted weak API key validation patterns",
                    repo="acme/webapp",
                ),
            ],
        ),
        provider_mode="mock",
        tags=["realistic", "auth", "authz", "memory", "provider-value"],
        security_focus=["authorization", "authentication"],
        provider_value_expected=True,
        expected=ExpectedBehavior(
            provider_gate_invoked=True,
            has_concerns=True,
            has_observations=True,
            markdown_contains=["Security Review"],
            no_trust_boundary_violations=True,
        ),
    )


# ------------------------------------------------------------------
# Realistic corpus registry
# ------------------------------------------------------------------


REALISTIC_SCENARIOS: list[ValidationScenario] = [
    _missing_auth_on_route(),
    _authz_business_logic(),
    _unsafe_sql_input(),
    _insecure_session_config(),
    _github_token_in_env(),
    _harmless_utility_refactor(),
    _docs_and_changelog(),
    _test_coverage_expansion(),
    _provider_helpful_auth(),
    _memory_recurring_vuln(),
]


def get_realistic_scenario(scenario_id: str) -> ValidationScenario | None:
    """Look up a realistic scenario by its unique id."""
    for s in REALISTIC_SCENARIOS:
        if s.id == scenario_id:
            return s
    return None


def list_realistic_ids() -> list[str]:
    """Return the ids of all realistic scenarios."""
    return [s.id for s in REALISTIC_SCENARIOS]
