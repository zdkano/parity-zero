"""Structured JSON findings contract for parity-zero.

This module defines the Pydantic models that form the core data contract
between the reviewer, the ingestion API, and all downstream consumers.

Every parity-zero scan MUST emit output conforming to these models.
Schema changes must be treated carefully — see ADR-003 and routing.md.

Categories are drawn from .squad/context/findings-taxonomy.md.
Severity and confidence are intentionally separate dimensions.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class Category(str, enum.Enum):
    """Finding categories from the parity-zero findings taxonomy."""

    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    INPUT_VALIDATION = "input_validation"
    SECRETS = "secrets"
    INSECURE_CONFIGURATION = "insecure_configuration"
    DEPENDENCY_RISK = "dependency_risk"


class Severity(str, enum.Enum):
    """Impact severity of a finding."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Confidence(str, enum.Enum):
    """Reviewer confidence in the finding.

    Separate from severity — a finding can be high severity but medium
    confidence.  See findings-taxonomy.md § Taxonomy rules.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Decision(str, enum.Enum):
    """Scan-level reviewer decision.

    Represents the reviewer's overall assessment of the pull request
    based on the aggregated findings.
    """

    BLOCK = "block"
    WARN = "warn"
    PASS = "pass"


class Finding(BaseModel):
    """A single security finding produced by the reviewer.

    Each finding maps to one taxonomy category, has independent severity
    and confidence ratings, and references the specific code location.
    """

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    category: Category
    severity: Severity
    confidence: Confidence
    title: str = Field(..., min_length=1, max_length=256)
    description: str = Field(..., min_length=1)
    file: str = Field(..., description="Path to the affected file relative to the repo root.")
    start_line: Optional[int] = Field(None, ge=1)
    end_line: Optional[int] = Field(None, ge=1)
    recommendation: Optional[str] = Field(
        None, description="Actionable guidance for the developer."
    )


class ScanMeta(BaseModel):
    """Scan-level metadata for a parity-zero review run.

    Captures the context of the scan — which repo, PR, commit, and when
    the scan occurred.  ScanResult inherits from this model so the
    metadata fields remain flat in the JSON contract.
    """

    scan_id: str = Field(default_factory=lambda: uuid4().hex)
    repo: str = Field(..., description="Owner/repo identifier, e.g. 'acme/webapp'.")
    pr_number: int = Field(..., ge=1)
    commit_sha: str = Field(..., min_length=7, max_length=40)
    ref: str = Field(..., description="Head branch ref of the pull request.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ScanResult(ScanMeta):
    """Top-level output of a single parity-zero review run.

    Wraps zero or more findings with metadata about the scan context.
    This is the payload sent to the ingestion API and the basis for the
    markdown PR summary.
    """

    decision: Decision = Field(
        default=Decision.PASS,
        description="Reviewer's overall assessment of the pull request.",
    )
    findings: list[Finding] = Field(default_factory=list)

    @property
    def summary_counts(self) -> dict[str, int]:
        """Return finding counts grouped by severity."""
        counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts
