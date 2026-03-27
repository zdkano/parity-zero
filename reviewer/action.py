"""GitHub Action entry point for the parity-zero reviewer.

This module is invoked by the GitHub Actions workflow (.github/workflows/review.yml).
It orchestrates the full review flow:

  1. Read PR metadata and changed files from the GitHub event context.
  2. Pass changed files to the analysis engine.
  3. Collect structured findings into a ScanResult.
  4. Format a markdown summary and post it as a PR comment / check output.
  5. Optionally send the ScanResult to the central ingestion API.

Phase 1 implementation parses real GitHub event context and discovers
changed files via the GitHub API.  Detection logic will be added
incrementally.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request

from schemas.findings import ScanResult
from reviewer.engine import analyse
from reviewer.formatter import format_markdown

logger = logging.getLogger(__name__)


def _load_event_payload() -> dict:
    """Load the GitHub Actions event payload from ``GITHUB_EVENT_PATH``.

    Returns an empty dict if the file is missing or contains invalid JSON.
    """
    path = os.getenv("GITHUB_EVENT_PATH", "")
    if not path:
        logger.warning("GITHUB_EVENT_PATH is not set; using fallback context.")
        return {}

    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, IsADirectoryError):
        logger.warning("Event payload file not found: %s", path)
        return {}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Malformed event payload at %s: %s", path, exc)
        return {}

    if not isinstance(data, dict):
        logger.warning("Event payload is not a JSON object.")
        return {}

    return data


def get_pr_context() -> dict:
    """Extract pull request context from the GitHub Actions environment.

    Parses ``GITHUB_EVENT_PATH`` for the ``pull_request`` event payload and
    falls back to environment variables when the payload is unavailable.

    Returns a dict with *repo*, *pr_number*, *commit_sha*, and *ref*.
    """
    event = _load_event_payload()
    pr = event.get("pull_request") or {}

    repo = (
        event.get("repository", {}).get("full_name")
        or os.getenv("GITHUB_REPOSITORY", "unknown/unknown")
    )

    _pr_number = pr.get("number")
    if _pr_number is None:
        _pr_number = event.get("number")
    if _pr_number is None:
        _pr_number = int(os.getenv("PR_NUMBER", "0"))
    pr_number = _pr_number

    _sha = pr.get("head", {}).get("sha")
    commit_sha = _sha if _sha is not None else os.getenv("GITHUB_SHA", "0000000")

    _ref = pr.get("head", {}).get("ref")
    ref = _ref if _ref is not None else os.getenv("GITHUB_HEAD_REF", "unknown")

    return {
        "repo": str(repo),
        "pr_number": int(pr_number),
        "commit_sha": str(commit_sha),
        "ref": str(ref),
    }


def get_changed_files(repo: str, pr_number: int) -> list[str]:
    """Return the list of files changed in the pull request.

    Uses the GitHub REST API to fetch changed files for the given PR.
    Files with status ``removed`` are excluded since there is no content
    to review.

    Args:
        repo: Owner/repo string, e.g. ``"acme/webapp"``.
        pr_number: Pull request number.

    Returns:
        Repo-relative file paths of added, modified, or renamed files.
        Returns an empty list if the API call fails or context is missing.
    """
    if not repo or repo == "unknown/unknown" or pr_number < 1:
        logger.warning("Insufficient PR context for changed-file discovery.")
        return []

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        logger.warning("GITHUB_TOKEN not set; cannot discover changed files.")
        return []

    api_url = os.getenv("GITHUB_API_URL", "https://api.github.com")

    changed: list[str] = []
    page = 1
    per_page = 100

    while True:
        url = (
            f"{api_url}/repos/{repo}/pulls/{pr_number}/files"
            f"?per_page={per_page}&page={page}"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

        try:
            with urllib.request.urlopen(req) as resp:
                files = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            logger.warning("GitHub API error fetching changed files: %s", exc)
            # Return partial results accumulated so far — reviewing some
            # files is better than reviewing none on a transient failure.
            return changed
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Malformed GitHub API response: %s", exc)
            return changed

        if not isinstance(files, list):
            break
        if not files:
            break

        for f in files:
            status = f.get("status", "")
            filename = f.get("filename", "")
            if status != "removed" and filename:
                changed.append(filename)

        if len(files) < per_page:
            break
        page += 1

    return changed


def run() -> None:
    """Execute the reviewer workflow."""
    context = get_pr_context()
    changed_files = get_changed_files(context["repo"], context["pr_number"])

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
