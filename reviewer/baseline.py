"""Baseline repository profiler for parity-zero.

Builds a lightweight ``RepoSecurityProfile`` from repository file inputs.
This provides the foundation for context-aware PR review — see ADR-015.

Phase 1 implementation performs basic, cheap detection of:
- likely programming languages (by file extension)
- obvious framework hints (by file name and simple content patterns)
- sensitive paths and directories
- coarse authentication-related signals

This is a **baseline context generator**, not a full scanner.  It does not
produce findings — it produces a profile that the contextual review engine
can use to make better-informed assessments during PR review.

Later iterations will enrich this with deeper analysis, AST-based detection,
and integration with repository metadata APIs.
"""

from __future__ import annotations

import os

from reviewer.models import BaselineScanResult, RepoSecurityProfile

# -- Language detection by file extension ------------------------------------

_EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".cs": "c#",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".c": "c",
    ".cpp": "c++",
    ".h": "c",
}

# -- Framework hints by filename or content ----------------------------------

_FRAMEWORK_FILE_HINTS: dict[str, str] = {
    "requirements.txt": "python-pip",
    "Pipfile": "python-pipenv",
    "pyproject.toml": "python-project",
    "package.json": "node",
    "Gemfile": "ruby-bundler",
    "Cargo.toml": "rust-cargo",
    "go.mod": "go-modules",
    "pom.xml": "java-maven",
    "build.gradle": "java-gradle",
    "composer.json": "php-composer",
    "Dockerfile": "docker",
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    "terraform.tf": "terraform",
    ".terraform.lock.hcl": "terraform",
}

_FRAMEWORK_CONTENT_HINTS: list[tuple[str, str]] = [
    ("from fastapi", "fastapi"),
    ("from flask", "flask"),
    ("from django", "django"),
    ("import express", "express"),
    ("from starlette", "starlette"),
    ("import spring", "spring"),
    ("from sqlalchemy", "sqlalchemy"),
    ("import mongoose", "mongoose"),
]

# -- Sensitive path patterns -------------------------------------------------

_SENSITIVE_PATH_SEGMENTS: list[str] = [
    "auth",
    "admin",
    "security",
    "secrets",
    "credentials",
    "keys",
    "certificates",
    "certs",
    "config",
    "settings",
    "deploy",
    "migration",
    "migrations",
    "middleware",
]

# -- Auth-related content signals --------------------------------------------

_AUTH_CONTENT_SIGNALS: list[tuple[str, str]] = [
    ("jwt", "JWT usage detected"),
    ("oauth", "OAuth reference detected"),
    ("bearer", "Bearer token handling detected"),
    ("password", "Password handling detected"),
    ("api_key", "API key handling detected"),
    ("api-key", "API key handling detected"),
    ("authentication", "Authentication logic detected"),
    ("authorization", "Authorization logic detected"),
]


def profile_repository(
    file_contents: dict[str, str],
    repo: str = "",
) -> BaselineScanResult:
    """Build a baseline security profile from repository file contents.

    Args:
        file_contents: Mapping of repo-relative file paths to their text
            content.  This may be a subset of the full repository.
        repo: Repository identifier (e.g. ``"acme/webapp"``).

    Returns:
        A ``BaselineScanResult`` containing the derived profile and
        profiling metadata.
    """
    languages: set[str] = set()
    frameworks: set[str] = set()
    sensitive_paths: list[str] = []
    auth_patterns: set[str] = set()
    notes: list[str] = []

    for path, content in file_contents.items():
        # -- Language detection --
        _, ext = os.path.splitext(path)
        if ext.lower() in _EXTENSION_LANGUAGE_MAP:
            languages.add(_EXTENSION_LANGUAGE_MAP[ext.lower()])

        # -- Framework hints by filename --
        basename = os.path.basename(path)
        if basename in _FRAMEWORK_FILE_HINTS:
            frameworks.add(_FRAMEWORK_FILE_HINTS[basename])

        # -- Framework hints by content --
        content_lower = content.lower()
        for pattern, framework in _FRAMEWORK_CONTENT_HINTS:
            if pattern.lower() in content_lower:
                frameworks.add(framework)

        # -- Sensitive path detection --
        path_lower = path.lower()
        for segment in _SENSITIVE_PATH_SEGMENTS:
            if segment in path_lower.split("/"):
                if path not in sensitive_paths:
                    sensitive_paths.append(path)
                break

        # -- Auth-related signals --
        for signal, description in _AUTH_CONTENT_SIGNALS:
            if signal in content_lower:
                auth_patterns.add(description)

    if not file_contents:
        notes.append("No files provided for baseline profiling.")
    else:
        notes.append(f"Baseline profile derived from {len(file_contents)} file(s).")

    profile = RepoSecurityProfile(
        repo=repo,
        languages=sorted(languages),
        frameworks=sorted(frameworks),
        sensitive_paths=sensitive_paths,
        auth_patterns=sorted(auth_patterns),
        notes=notes,
    )

    return BaselineScanResult(
        profile=profile,
        files_analysed=len(file_contents),
        notes=notes,
    )
