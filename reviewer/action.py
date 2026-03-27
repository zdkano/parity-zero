"""GitHub Action entry point for the parity-zero reviewer.

This module is invoked by the GitHub Actions workflow (.github/workflows/review.yml).
It orchestrates the full review flow:

  1. Read PR metadata and changed files from the GitHub event context.
  2. Pass changed files to the analysis engine.
  3. Collect structured findings into a ScanResult.
  4. Format a markdown summary and post it as a PR comment / check output.
  5. Optionally send the ScanResult to the central ingestion API.

Phase 1 implementation is a placeholder that demonstrates the intended
orchestration.  Detection logic will be added incrementally.
"""

from __future__ import annotations

import json
import os
import sys

from schemas.findings import ScanResult
from reviewer.engine import analyse
from reviewer.formatter import format_markdown


def get_pr_context() -> dict:
    """Extract pull request context from the GitHub Actions environment.

    Returns a dict with repo, pr_number, commit_sha, and ref.
    In a real run these come from GITHUB_EVENT_PATH and environment variables.
    """
    # TODO: Parse GITHUB_EVENT_PATH JSON for full event payload.
    return {
        "repo": os.getenv("GITHUB_REPOSITORY", "unknown/unknown"),
        "pr_number": int(os.getenv("PR_NUMBER", "0")),
        "commit_sha": os.getenv("GITHUB_SHA", "0000000"),
        "ref": os.getenv("GITHUB_HEAD_REF", "unknown"),
    }


def get_changed_files() -> list[str]:
    """Return the list of files changed in the pull request.

    TODO: Use the GitHub API or git diff to determine changed files.
    """
    return []


def run() -> None:
    """Execute the reviewer workflow."""
    context = get_pr_context()
    changed_files = get_changed_files()

    findings = analyse(changed_files)

    result = ScanResult(
        repo=context["repo"],
        pr_number=context["pr_number"],
        commit_sha=context["commit_sha"],
        ref=context["ref"],
        findings=findings,
    )

    # Emit structured JSON to stdout (core contract).
    print(result.model_dump_json(indent=2))

    # Generate and emit markdown summary.
    markdown = format_markdown(result)
    print("\n--- Markdown Summary ---\n")
    print(markdown)

    # TODO: Post markdown as a PR comment via GitHub API.
    # TODO: Optionally send result to ingestion API.


if __name__ == "__main__":
    run()
