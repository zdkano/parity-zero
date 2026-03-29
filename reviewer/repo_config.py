"""Repo-level configuration for parity-zero (ADR-041).

Loads and validates an optional ``.parity-zero.yml`` configuration file
from the repository root.  The config allows repository owners to
customise reviewer behavior with:

- **exclude_paths** — paths excluded from meaningful review processing.
- **low_signal_paths** — paths reviewable but treated as lower priority.
- **provider_skip_paths** — paths where live provider reasoning is skipped.

All path matching uses glob-style patterns via :func:`fnmatch.fnmatch`.

When the config file is absent, parity-zero behaves exactly as it does
without configuration.  When the file is present but invalid, loading
fails safely with a clear warning and returns an empty (no-op) config.

The config shape is intentionally narrow today but designed so that
future settings (suppressions, focus paths, repo criticality, provider
policies, trust settings) can be added without a redesign.

See ADR-041 and ``docs/repo-config.md`` for details.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# The canonical config filename, looked up in the repo root.
CONFIG_FILENAME = ".parity-zero.yml"

# Fields allowed at the top level of the config.
_ALLOWED_TOP_LEVEL_KEYS = frozenset({
    "exclude_paths",
    "low_signal_paths",
    "provider_skip_paths",
})


@dataclass(frozen=True)
class RepoConfig:
    """Validated repo-level configuration.

    All path lists use glob patterns matched by :func:`fnmatch.fnmatch`.
    An empty ``RepoConfig`` (the default) is a no-op — it has no effect
    on the reviewer pipeline.

    Attributes:
        exclude_paths: Glob patterns for paths excluded from review.
            Excluded files are not loaded into review content, do not
            drive findings/concerns/observations, and do not trigger
            provider reasoning.  Path-level metadata may still be
            retained for transparency (e.g. as skipped files).
        low_signal_paths: Glob patterns for paths that remain reviewable
            but receive quieter treatment — reduced observation/concern
            generation and stronger quietness expectations.
        provider_skip_paths: Glob patterns for paths where live provider
            reasoning should not run.  The rest of the pipeline (including
            deterministic checks) still processes these files.
    """

    exclude_paths: tuple[str, ...] = ()
    low_signal_paths: tuple[str, ...] = ()
    provider_skip_paths: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # Predicate helpers
    # ------------------------------------------------------------------

    def is_excluded(self, path: str) -> bool:
        """Return True if *path* matches any ``exclude_paths`` glob."""
        return _matches_any(path, self.exclude_paths)

    def is_low_signal(self, path: str) -> bool:
        """Return True if *path* matches any ``low_signal_paths`` glob."""
        return _matches_any(path, self.low_signal_paths)

    def is_provider_skip(self, path: str) -> bool:
        """Return True if *path* matches any ``provider_skip_paths`` glob."""
        return _matches_any(path, self.provider_skip_paths)

    @property
    def is_empty(self) -> bool:
        """True when the config has no configured paths (no-op)."""
        return not self.exclude_paths and not self.low_signal_paths and not self.provider_skip_paths


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    """Return True if *path* matches at least one glob pattern.

    Matching is performed against both the full path and each path
    component suffix so that a pattern like ``docs/**`` matches
    ``docs/readme.md`` and a pattern like ``*.lock`` matches
    ``packages/yarn.lock``.
    """
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return True
        # Also match against the basename for simple patterns.
        if fnmatch.fnmatch(os.path.basename(path), pattern):
            return True
    return False


# ------------------------------------------------------------------
# Loading and validation
# ------------------------------------------------------------------


def load_config(repo_root: str | None = None) -> RepoConfig:
    """Load repo-level config from ``.parity-zero.yml`` in *repo_root*.

    Args:
        repo_root: Directory to look for the config file.  Defaults to
            the current working directory.

    Returns:
        A validated ``RepoConfig``.  Returns an empty config when the
        file is absent.  Returns an empty config (with a logged warning)
        when the file is present but invalid.
    """
    if repo_root is None:
        repo_root = os.getcwd()

    config_path = os.path.join(repo_root, CONFIG_FILENAME)

    if not os.path.isfile(config_path):
        return RepoConfig()

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        # If PyYAML is not installed, log and return empty config.
        logger.warning(
            "PyYAML is not installed; cannot load %s. "
            "Install pyyaml to enable repo-level configuration.",
            config_path,
        )
        return RepoConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception as exc:
        logger.warning(
            "Failed to read %s: %s. Using default configuration.",
            config_path, exc,
        )
        return RepoConfig()

    return _validate_raw(raw, config_path)


def load_config_from_text(text: str) -> RepoConfig:
    """Load repo-level config from a YAML string.

    Convenience helper for testing and programmatic use.

    Args:
        text: YAML text to parse.

    Returns:
        A validated ``RepoConfig``.  Returns an empty config (with a
        logged warning) when the text is invalid.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML is not installed; returning empty config.")
        return RepoConfig()

    try:
        raw = yaml.safe_load(text)
    except Exception as exc:
        logger.warning("Invalid YAML config text: %s", exc)
        return RepoConfig()

    return _validate_raw(raw, "<text>")


def _validate_raw(raw: Any, source: str) -> RepoConfig:
    """Validate parsed YAML and return a ``RepoConfig``.

    Validation rules:
    - Top-level value must be a dict (or None/empty for no-op).
    - Only recognised keys are allowed.
    - Each path list must be a list of non-empty strings.
    - Invalid config logs a clear warning and returns an empty config.
    """
    if raw is None:
        return RepoConfig()

    if not isinstance(raw, dict):
        logger.warning(
            "%s: config must be a YAML mapping, got %s. Using defaults.",
            source, type(raw).__name__,
        )
        return RepoConfig()

    unknown_keys = set(raw.keys()) - _ALLOWED_TOP_LEVEL_KEYS
    if unknown_keys:
        logger.warning(
            "%s: unrecognised config keys: %s. Using defaults.",
            source, ", ".join(sorted(unknown_keys)),
        )
        return RepoConfig()

    errors: list[str] = []

    exclude = _validate_path_list(raw.get("exclude_paths"), "exclude_paths", errors)
    low_signal = _validate_path_list(raw.get("low_signal_paths"), "low_signal_paths", errors)
    provider_skip = _validate_path_list(raw.get("provider_skip_paths"), "provider_skip_paths", errors)

    if errors:
        logger.warning(
            "%s: invalid config — %s. Using defaults.",
            source, "; ".join(errors),
        )
        return RepoConfig()

    return RepoConfig(
        exclude_paths=tuple(exclude),
        low_signal_paths=tuple(low_signal),
        provider_skip_paths=tuple(provider_skip),
    )


def _validate_path_list(
    value: Any,
    field_name: str,
    errors: list[str],
) -> list[str]:
    """Validate a single path-list field.

    Returns a list of valid glob strings.  Appends to *errors* on
    validation failure.
    """
    if value is None:
        return []

    if not isinstance(value, list):
        errors.append(f"{field_name} must be a list, got {type(value).__name__}")
        return []

    result: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field_name}[{i}] must be a non-empty string")
            return []
        result.append(item.strip())

    return result


# ------------------------------------------------------------------
# Pipeline integration helpers
# ------------------------------------------------------------------


def filter_excluded_paths(
    file_contents: dict[str, str],
    config: RepoConfig,
) -> tuple[dict[str, str], list[str]]:
    """Remove excluded paths from file contents.

    Args:
        file_contents: ``{path: content}`` mapping.
        config: Repo-level configuration.

    Returns:
        A tuple of ``(filtered_contents, excluded_paths)`` where
        ``excluded_paths`` lists the paths that were removed.
    """
    if config.is_empty:
        return file_contents, []

    filtered: dict[str, str] = {}
    excluded: list[str] = []

    for path, content in file_contents.items():
        if config.is_excluded(path):
            excluded.append(path)
        else:
            filtered[path] = content

    return filtered, excluded


def all_provider_skip(paths: list[str], config: RepoConfig) -> bool:
    """Return True if every path in *paths* matches ``provider_skip_paths``.

    Used by the provider gate to decide whether provider reasoning should
    be skipped entirely for a PR where all changed files are in
    provider-skip paths.
    """
    if not paths or config.is_empty:
        return False
    return all(config.is_provider_skip(p) for p in paths)
