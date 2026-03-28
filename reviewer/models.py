"""PR content and repository context models for the parity-zero reviewer.

Provides explicit structures for:

- **PR file inputs** — ``PRFile``, ``SkippedFile``, and ``PRContent`` (ADR-011, ADR-036).
- **Repository security profile** — ``RepoSecurityProfile`` representing
  the baseline security context of a repository (ADR-015).
- **Baseline scan result** — ``BaselineScanResult`` capturing the output
  of a baseline profiling run.
- **Review memory** — ``ReviewMemoryEntry`` and ``ReviewMemory`` for
  persistent review context that accumulates over time (ADR-016).
- **Pull request context** — ``PullRequestContext`` combining PR delta
  with baseline profile and review memory (ADR-018).
- **Review bundle** — ``ReviewBundleItem`` and ``ReviewBundle`` for
  structured review evidence aggregation (ADR-023).
- **Review observation** — ``ReviewObservation`` for per-file security
  review observations derived from ReviewBundle items (ADR-024).
- **Review trace** — ``ReviewTrace`` for internal reviewer traceability
  capturing why the reviewer behaved the way it did (ADR-030).

Phase 1 keeps models deliberately minimal — see relevant ADRs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


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


@dataclass(frozen=True)
class SkippedFile:
    """A changed file whose content could not be loaded.

    Preserves path-level awareness that a file changed even when the
    content is unavailable (deleted, binary, too large, or unreadable).
    The ``reason`` field explains why content was not loaded.

    See ADR-036 for the decision to preserve skipped-file metadata.
    """

    path: str
    reason: str


@dataclass
class PRContent:
    """Collection of changed files in a pull request.

    This is the primary input structure for the analysis engine.
    It wraps one or more PRFile instances and provides convenience
    methods for interoperability with the existing ``dict[str, str]``
    interfaces used by checks and reasoning modules.

    Changed files whose content could not be loaded are tracked in
    ``skipped_files`` — see ``SkippedFile`` and ADR-036.
    """

    files: list[PRFile] = field(default_factory=list)
    skipped_files: list[SkippedFile] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        file_contents: dict[str, str],
        skipped: list[SkippedFile] | None = None,
    ) -> PRContent:
        """Create a PRContent from a ``{path: content}`` mapping.

        This is the primary migration path from the legacy dict-based
        interface.

        Args:
            file_contents: ``{path: content}`` mapping for loaded files.
            skipped: Optional list of ``SkippedFile`` entries for files
                whose content could not be loaded.
        """
        return cls(
            files=[PRFile(path=p, content=c) for p, c in file_contents.items()],
            skipped_files=skipped or [],
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
    def skipped_file_count(self) -> int:
        """Number of changed files whose content could not be loaded."""
        return len(self.skipped_files)

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
    profiled_at: str = field(default_factory=_utc_now_iso)


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
    recorded_at: str = field(default_factory=_utc_now_iso)


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
# Review plan (ADR-021)
# ======================================================================


@dataclass
class ReviewPlan:
    """Structured review plan derived from PR delta, baseline, and memory.

    The review plan bridges raw context and contextual review reasoning.
    It captures which areas of the PR warrant elevated review attention
    based on path overlap, baseline awareness, and historical memory.

    The plan **guides** review attention — it does not claim vulnerabilities
    or produce findings directly.

    Phase 1: lightweight, heuristic-based plan derivation.  Later phases
    will incorporate provider-backed reasoning into plan construction.
    """

    focus_areas: list[str] = field(default_factory=list)
    """Finding categories relevant to this PR (e.g. 'authorization')."""

    review_flags: list[str] = field(default_factory=list)
    """Elevated attention flags (e.g. 'touches_sensitive_path')."""

    sensitive_paths_touched: list[str] = field(default_factory=list)
    """Changed paths that overlap with sensitive areas."""

    auth_paths_touched: list[str] = field(default_factory=list)
    """Changed paths that overlap with auth-related areas."""

    relevant_memory_categories: list[str] = field(default_factory=list)
    """Historical review memory categories relevant to this PR."""

    framework_context: list[str] = field(default_factory=list)
    """Frameworks detected in the repository baseline."""

    auth_pattern_context: list[str] = field(default_factory=list)
    """Auth patterns detected in the repository baseline."""

    reviewer_guidance: list[str] = field(default_factory=list)
    """Accumulated guidance notes for downstream reasoning stages."""


# ======================================================================
# Review concern (ADR-022)
# ======================================================================


@dataclass
class ReviewConcern:
    """A contextual security concern derived from the review plan.

    Review concerns represent areas that **may deserve closer attention**
    based on PR delta, baseline context, and review memory.  They are
    explicitly **not** proven findings — they preserve uncertainty honestly
    and surface plausible security concern areas.

    Concerns are:
    - distinct from ``Finding`` — they do not claim a vulnerability
    - surfaced in markdown output only (not in the JSON contract)
    - not used in risk scoring unless explicitly designed to do so
    - lightweight, testable, and phase-1-appropriate

    See ADR-022 for the decision to introduce this concept.
    """

    category: str = ""
    """Finding taxonomy category this concern relates to."""

    title: str = ""
    """Concise concern title."""

    summary: str = ""
    """Context-aware description of why this area deserves attention."""

    confidence: str = "low"
    """How confident the reviewer is this concern is relevant (high/medium/low)."""

    basis: str = ""
    """Source of the concern (e.g. 'sensitive_path_overlap', 'memory_match')."""

    related_paths: list[str] = field(default_factory=list)
    """File paths related to this concern."""


# ======================================================================
# Review observation (ADR-024)
# ======================================================================


@dataclass
class ReviewObservation:
    """A targeted security review observation tied to a specific changed file.

    Review observations explain **why a particular file deserves scrutiny**
    based on its ReviewBundleItem context — focus areas, baseline context,
    memory context, and review reason.  They are per-file, contextual, and
    reviewer-like.

    Observations are:
    - distinct from ``Finding`` — they do not claim a vulnerability
    - distinct from ``ReviewConcern`` — they are tied to specific files
      and derived from ReviewBundle evidence rather than plan-level signals
    - surfaced in markdown output only (not in the JSON contract)
    - not used in risk scoring
    - lightweight, heuristic-based, and phase-1-appropriate

    See ADR-024 for the decision to introduce this concept.
    """

    path: str = ""
    """Repo-relative file path this observation targets."""

    focus_area: str = ""
    """Primary finding taxonomy area relevant to this observation."""

    title: str = ""
    """Concise observation title."""

    summary: str = ""
    """Context-aware description of why this file deserves scrutiny."""

    confidence: str = "low"
    """How confident the reviewer is this observation is relevant (medium/low)."""

    basis: str = ""
    """Source of the observation (e.g. 'auth_bundle_item', 'memory_alignment')."""

    related_paths: list[str] = field(default_factory=list)
    """Other changed paths related to this observation."""


# ======================================================================
# Review bundle (ADR-023)
# ======================================================================


@dataclass
class ReviewBundleItem:
    """A single file under review with its gathered context.

    Each item represents one changed file together with the evidence
    explaining why it is included in the review and what surrounding
    context is relevant.  Items are deliberately lightweight — they
    carry just enough information to support better contextual review
    inputs without attempting full AST or code-graph analysis.

    See ADR-023 for the decision to introduce the review bundle concept.
    """

    path: str = ""
    """Repo-relative file path."""

    content: str = ""
    """Changed file content (full text, as provided by PRFile)."""

    review_reason: str = ""
    """Why this file is in review focus (e.g. 'sensitive_path', 'auth_area', 'changed_file')."""

    focus_areas: list[str] = field(default_factory=list)
    """Finding categories relevant to this file from ReviewPlan."""

    baseline_context: list[str] = field(default_factory=list)
    """Relevant baseline information (frameworks, auth patterns)."""

    memory_context: list[str] = field(default_factory=list)
    """Relevant historical review memory entries."""

    related_paths: list[str] = field(default_factory=list)
    """Other changed paths that share review context with this file."""


@dataclass
class ReviewBundle:
    """Structured review evidence aggregation for contextual review.

    Gathers the relevant evidence and surrounding context for security
    review.  Sits between ``PullRequestContext`` / ``ReviewPlan`` and
    the contextual review / future reasoning layers.

    The bundle captures enough information to support better contextual
    review later, including:
    - changed file paths with content
    - why each item is in review focus
    - relevant baseline profile context
    - relevant memory context
    - related context paths when easily derivable

    The bundle is intentionally lightweight and heuristic-based in Phase 1.
    It does **not** appear in the ScanResult JSON contract and does **not**
    affect risk scoring.

    See ADR-023 for the decision record.
    """

    items: list[ReviewBundleItem] = field(default_factory=list)
    """Individual file review items with gathered context."""

    plan_summary: list[str] = field(default_factory=list)
    """Reviewer guidance from the ReviewPlan."""

    repo_frameworks: list[str] = field(default_factory=list)
    """Frameworks detected in the repository baseline."""

    repo_auth_patterns: list[str] = field(default_factory=list)
    """Auth patterns detected in the repository baseline."""

    @property
    def item_count(self) -> int:
        """Number of items in the bundle."""
        return len(self.items)

    @property
    def sensitive_items(self) -> list[ReviewBundleItem]:
        """Items whose review reason involves sensitive paths."""
        return [i for i in self.items if "sensitive" in i.review_reason]

    @property
    def auth_items(self) -> list[ReviewBundleItem]:
        """Items whose review reason involves auth areas."""
        return [i for i in self.items if "auth" in i.review_reason]

    @property
    def has_high_focus_items(self) -> bool:
        """Whether any items have non-trivial review focus."""
        return any(
            i.review_reason not in ("", "changed_file")
            for i in self.items
        )


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


# ======================================================================
# Review trace (ADR-030)
# ======================================================================


@dataclass
class ReviewTrace:
    """Internal traceability record for a single reviewer run.

    Captures key signals about why the reviewer behaved the way it did
    during a review.  Intended for debugging, tuning, trust calibration,
    and future control-plane design.

    The trace is **internal only**.  It does not appear in:
    - ``ScanResult`` JSON contract
    - ingestion payloads
    - risk scoring or decision derivation
    - markdown output

    See ADR-030 for the decision to introduce this concept.
    """

    provider_attempted: bool = False
    """Whether provider reasoning invocation was attempted."""

    provider_gate_decision: str = ""
    """Gate outcome: 'invoked', 'skipped', 'disabled', 'unavailable', or ''."""

    provider_gate_reasons: list[str] = field(default_factory=list)
    """Explainable reasons from provider invocation gating."""

    provider_name: str = ""
    """Name of the reasoning provider used (if any)."""

    active_focus_areas: list[str] = field(default_factory=list)
    """Focus areas active from the ReviewPlan."""

    bundle_item_count: int = 0
    """Number of items in the ReviewBundle."""

    bundle_high_focus_count: int = 0
    """Number of bundle items with elevated review focus."""

    concern_count: int = 0
    """Number of ReviewConcern instances generated."""

    observation_count: int = 0
    """Number of ReviewObservation instances generated."""

    provider_notes_returned: int = 0
    """Raw candidate notes returned by the provider."""

    provider_notes_suppressed: int = 0
    """Provider notes suppressed by overlap filtering."""

    provider_notes_kept: int = 0
    """Provider notes retained after overlap suppression."""

    observation_refinement_applied: bool = False
    """Whether provider-backed observation refinement ran."""

    entries: list[str] = field(default_factory=list)
    """Ordered descriptive entries documenting reviewer decisions."""
