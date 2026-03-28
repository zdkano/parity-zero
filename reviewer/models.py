"""PR content and repository context models for the parity-zero reviewer.

Provides explicit structures for:

- **PR file inputs** — ``PRFile`` and ``PRContent`` (ADR-011).
- **Repository security profile** — ``RepoSecurityProfile`` representing
  the baseline security context of a repository (ADR-015).
- **Baseline scan result** — ``BaselineScanResult`` capturing the output
  of a baseline profiling run.
- **Review memory** — ``ReviewMemoryEntry`` and ``ReviewMemory`` for
  persistent review context that accumulates over time (ADR-016).
- **Pull request context** — ``PullRequestContext`` combining PR delta
  with baseline profile and review memory (ADR-018).

Phase 1 keeps models deliberately minimal — see relevant ADRs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


# ======================================================================
# PR file models (ADR-011)
# ======================================================================


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


# ======================================================================
# Repository security profile (ADR-015)
# ======================================================================


@dataclass
class RepoSecurityProfile:
    """Lightweight security profile of a repository.

    Captures baseline context that makes subsequent PR reviews
    repository-aware rather than stateless.

    Phase 1: populated by the baseline profiler stub with basic
    language, framework, and sensitive-path detection.  Later iterations
    will enrich this with deeper analysis.
    """

    repo: str = ""
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    sensitive_paths: list[str] = field(default_factory=list)
    auth_patterns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    profiled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class BaselineScanResult:
    """Output of a baseline repository profiling run.

    Wraps a ``RepoSecurityProfile`` with metadata about the profiling
    run itself (file count, duration notes, etc.).
    """

    profile: RepoSecurityProfile = field(default_factory=RepoSecurityProfile)
    files_analysed: int = 0
    notes: list[str] = field(default_factory=list)


# ======================================================================
# Review memory (ADR-016)
# ======================================================================


@dataclass
class ReviewMemoryEntry:
    """A single entry in review memory.

    Represents a piece of accumulated review context — such as a prior
    finding theme, a recurring pattern, or a baseline observation.

    Phase 1: these are in-memory structures only.  Persistence is
    deferred to Phase 2+.
    """

    category: str = ""
    summary: str = ""
    repo: str = ""
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ReviewMemory:
    """Accumulated review memory for a repository.

    Holds a collection of memory entries that the contextual review
    engine can use to make better-informed assessments.

    Phase 1: populated manually or by stub logic.  Full persistence
    and retrieval deferred to Phase 2+.
    """

    repo: str = ""
    entries: list[ReviewMemoryEntry] = field(default_factory=list)

    @property
    def entry_count(self) -> int:
        """Number of entries in memory."""
        return len(self.entries)

    def categories(self) -> list[str]:
        """Return distinct categories present in memory."""
        return list(dict.fromkeys(e.category for e in self.entries if e.category))


# ======================================================================
# Pull request context (ADR-018)
# ======================================================================


@dataclass
class PullRequestContext:
    """Unified context object combining PR delta with repo context and memory.

    This is the intended primary input to the contextual review engine.
    It carries:
    - changed files (``pr_content``)
    - baseline repository profile (``baseline_profile``, optional)
    - review memory (``memory``, optional)

    Phase 1: baseline_profile and memory are typically None.  They
    become populated as baseline profiling and memory capabilities
    mature.

    Backward compatibility: the engine also accepts ``PRContent`` or
    ``dict[str, str]`` directly — see ADR-018.
    """

    pr_content: PRContent = field(default_factory=PRContent)
    baseline_profile: RepoSecurityProfile | None = None
    memory: ReviewMemory | None = None

    @classmethod
    def from_pr_content(cls, pr_content: PRContent) -> PullRequestContext:
        """Create a PullRequestContext from PRContent without baseline or memory."""
        return cls(pr_content=pr_content)

    @classmethod
    def from_dict(cls, file_contents: dict[str, str]) -> PullRequestContext:
        """Create a PullRequestContext from a legacy ``{path: content}`` dict."""
        return cls(pr_content=PRContent.from_dict(file_contents))

    @property
    def file_count(self) -> int:
        """Number of changed files."""
        return self.pr_content.file_count

    @property
    def has_baseline(self) -> bool:
        """Whether a baseline profile is attached."""
        return self.baseline_profile is not None

    @property
    def has_memory(self) -> bool:
        """Whether review memory is attached."""
        return self.memory is not None
