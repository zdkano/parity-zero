"""PR content abstraction for the parity-zero reviewer.

Provides a simple, explicit structure for representing pull request file
inputs.  This decouples the analysis engine from raw ``dict[str, str]``
and establishes a seam for future metadata enrichment (file status,
language, diff hunks, etc.).

Phase 1 keeps this deliberately minimal — see ADR-011.

Later considerations:
  - PRFile may carry ``status`` (added/modified/renamed), ``language``,
    or diff hunk metadata once real GitHub API integration is wired in.
  - PRContent construction should eventually be driven by the GitHub
    changed-files API response rather than manual dict conversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PRFile:
    """A single file from a pull request.

    Attributes:
        path: Repo-relative file path (e.g. ``"src/config.py"``).
        content: Full text content of the file.
    """

    path: str
    content: str


@dataclass
class PRContent:
    """Collection of changed files in a pull request.

    This is the primary input structure for the analysis engine.
    It wraps one or more PRFile instances and provides convenience
    methods for interoperability with the existing ``dict[str, str]``
    interfaces used by checks and reasoning modules.
    """

    files: list[PRFile] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, file_contents: dict[str, str]) -> PRContent:
        """Create a PRContent from a ``{path: content}`` mapping.

        This is the primary migration path from the legacy dict-based
        interface.
        """
        return cls(
            files=[PRFile(path=p, content=c) for p, c in file_contents.items()]
        )

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, str]:
        """Convert back to a ``{path: content}`` mapping.

        Used internally to feed modules that still operate on raw dicts
        (checks, reasoning) during Phase 1.
        """
        return {f.path: f.content for f in self.files}

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def file_count(self) -> int:
        """Number of files in this PR content."""
        return len(self.files)

    @property
    def paths(self) -> list[str]:
        """Return all file paths."""
        return [f.path for f in self.files]
