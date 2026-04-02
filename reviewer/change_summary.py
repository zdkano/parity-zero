"""Deterministic change summary for parity-zero PR reviews (ADR-047).

Generates a short, factual, bulleted summary of what changed in a PR.
The summary is deterministic — derived from changed file paths, review
bundle metadata, and review plan signals.  It does not interpret or
judge; that remains the provider review's job.

The summary helps developers quickly orient themselves before reading
the detailed security review.

Design:
  - factual, not judgmental
  - compact bullet list
  - derived from bundle/plan context already available
  - no new summarization engine or LLM call
"""

from __future__ import annotations

import re
from collections import defaultdict

from reviewer.models import ReviewBundle, ReviewPlan


# Path segment classifiers — map directory/file patterns to change types.
_ROUTE_SEGMENTS = {"routes", "router", "routers", "endpoints", "api"}
_CONTROLLER_SEGMENTS = {"controllers", "controller", "handlers", "handler", "views"}
_VALIDATION_SEGMENTS = {"validation", "validators", "validator", "schema", "schemas"}
_MODEL_SEGMENTS = {"models", "model", "entities", "entity"}
_AUTH_SEGMENTS = {"auth", "authentication", "login", "oauth", "session", "permissions", "rbac", "acl"}
_MIDDLEWARE_SEGMENTS = {"middleware", "middlewares"}
_CONFIG_SEGMENTS = {"config", "configuration", "settings", "deploy", "deployment"}
_TEST_SEGMENTS = {"test", "tests", "spec", "specs", "__tests__"}
_MIGRATION_SEGMENTS = {"migrations", "migration", "migrate"}
_SERVICE_SEGMENTS = {"services", "service"}

# Content patterns that signal specific change types.
_ROUTE_CONTENT_PATTERNS = [
    re.compile(r"@(app|router|blueprint)\.(get|post|put|patch|delete|route)\(", re.IGNORECASE),
    re.compile(r"router\.(get|post|put|patch|delete)\(", re.IGNORECASE),
    re.compile(r"app\.(get|post|put|patch|delete)\(", re.IGNORECASE),
    re.compile(r"@(Get|Post|Put|Patch|Delete|Route)Mapping", re.IGNORECASE),
    re.compile(r"urlpatterns\s*=", re.IGNORECASE),
]

_AUTH_CONTENT_PATTERNS = [
    re.compile(r"(authenticate|authorize|verify_token|check_auth|require_auth|login|logout)", re.IGNORECASE),
    re.compile(r"(jwt|bearer|session|cookie|oauth|api_key)", re.IGNORECASE),
    re.compile(r"@(requires_auth|login_required|authenticated)", re.IGNORECASE),
]

_VALIDATION_CONTENT_PATTERNS = [
    re.compile(r"(validate|sanitize|escape|parameterize|whitelist|allowlist)", re.IGNORECASE),
    re.compile(r"(Joi\.|yup\.|zod\.|Schema\(|validator)", re.IGNORECASE),
]


def build_change_summary(
    bundle: ReviewBundle | None = None,
    plan: ReviewPlan | None = None,
) -> list[str]:
    """Build a factual, deterministic change summary from review context.

    Returns a list of short bullet strings describing what changed.
    Returns an empty list when there is nothing meaningful to summarize.

    Args:
        bundle: Review bundle with per-file items and metadata.
        plan: Review plan with focus areas and flags.

    Returns:
        List of concise factual bullet strings (without leading ``-``).
    """
    if bundle is None or not bundle.items:
        return []

    bullets: list[str] = []
    change_types: dict[str, list[str]] = defaultdict(list)

    for item in bundle.items:
        path = item.path
        path_lower = path.lower()
        segments = set(path_lower.replace("\\", "/").split("/"))
        filename = path_lower.rsplit("/", 1)[-1] if "/" in path_lower else path_lower

        # Classify by path segments
        classified = False

        if segments & _ROUTE_SEGMENTS or _has_content_signal(item.content, _ROUTE_CONTENT_PATTERNS):
            change_types["route"].append(path)
            classified = True

        if segments & _CONTROLLER_SEGMENTS:
            change_types["controller"].append(path)
            classified = True

        if segments & _AUTH_SEGMENTS or _has_content_signal(item.content, _AUTH_CONTENT_PATTERNS):
            # Only count as auth if the path or content specifically suggests auth
            if segments & _AUTH_SEGMENTS or item.review_reason in ("sensitive_auth", "auth_area"):
                change_types["auth"].append(path)
                classified = True

        if segments & _MIDDLEWARE_SEGMENTS:
            change_types["middleware"].append(path)
            classified = True

        if segments & _VALIDATION_SEGMENTS or _has_content_signal(item.content, _VALIDATION_CONTENT_PATTERNS):
            change_types["validation"].append(path)
            classified = True

        if segments & _MODEL_SEGMENTS:
            change_types["model"].append(path)
            classified = True

        if segments & _CONFIG_SEGMENTS:
            change_types["config"].append(path)
            classified = True

        if segments & _TEST_SEGMENTS or filename.startswith("test_") or filename.endswith("_test.py"):
            change_types["test"].append(path)
            classified = True

        if segments & _MIGRATION_SEGMENTS:
            change_types["migration"].append(path)
            classified = True

        if segments & _SERVICE_SEGMENTS:
            change_types["service"].append(path)
            classified = True

        if not classified:
            change_types["other"].append(path)

    # Build bullets in a stable, useful order
    _add_bullet(bullets, change_types, "route", "route/endpoint")
    _add_bullet(bullets, change_types, "controller", "controller/handler")
    _add_bullet(bullets, change_types, "auth", "authentication/authorization")
    _add_bullet(bullets, change_types, "middleware", "middleware")
    _add_bullet(bullets, change_types, "validation", "validation")
    _add_bullet(bullets, change_types, "model", "model/schema")
    _add_bullet(bullets, change_types, "service", "service")
    _add_bullet(bullets, change_types, "config", "configuration")
    _add_bullet(bullets, change_types, "migration", "database migration")
    _add_bullet(bullets, change_types, "test", "test")

    # Add plan flags as context if meaningful
    if plan is not None:
        if "api_surface_expansion" in plan.review_flags:
            if not any("route" in b.lower() or "endpoint" in b.lower() for b in bullets):
                bullets.append("New API surface introduced")

    # If no classified bullets and only other files, produce a minimal summary
    if not bullets and change_types.get("other"):
        count = len(change_types["other"])
        bullets.append(f"{count} file(s) changed")

    return bullets


def _add_bullet(
    bullets: list[str],
    change_types: dict[str, list[str]],
    key: str,
    label: str,
) -> None:
    """Add a bullet for the given change type if files exist."""
    files = change_types.get(key)
    if not files:
        return
    count = len(files)
    if count == 1:
        short_path = files[0].rsplit("/", 1)[-1] if "/" in files[0] else files[0]
        bullets.append(f"{label.capitalize()} changed: `{short_path}`")
    else:
        bullets.append(f"{count} {label} file(s) changed")


def _has_content_signal(content: str, patterns: list[re.Pattern]) -> bool:
    """Check if file content matches any of the given patterns."""
    if not content:
        return False
    # Only check the first 3000 chars to keep it fast
    sample = content[:3000]
    return any(p.search(sample) for p in patterns)


def format_change_summary(bullets: list[str]) -> str:
    """Format change summary bullets into markdown.

    Returns an empty string when there are no bullets.
    """
    if not bullets:
        return ""

    lines = [
        "### 📝 What Changed",
        "",
    ]
    for bullet in bullets:
        lines.append(f"- {bullet}")
    lines.append("")

    return "\n".join(lines)
