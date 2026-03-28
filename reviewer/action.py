"""GitHub Action entry point for the parity-zero reviewer.

This module is invoked by the GitHub Actions workflow (.github/workflows/review.yml).
It orchestrates the full review flow:

  1. Read PR metadata and changed files from the GitHub event context.
  2. Pass changed file contents to the analysis engine.
  3. Derive decision and risk_score from the findings.
  4. Collect structured findings into a ScanResult.
  5. Format a markdown summary and post it as a PR comment / check output.
  6. Optionally send the ScanResult to the central ingestion API.

Phase 1 implementation parses real GitHub event context and discovers
changed files via the GitHub API.  The deterministic checks detect
insecure configuration patterns in file contents.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request

from schemas.findings import ScanResult
from reviewer.engine import analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.github_runtime import (
    discover_changed_files,
    load_file_contents,
    post_pr_comment,
    write_job_summary,
)
from reviewer.models import PRContent
from reviewer.provider_config import resolve_provider

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
    event = _load_event_payload()

    # Discover changed files — prefer git diff, fall back to API
    changed_files = discover_changed_files(event)
    if not changed_files:
        changed_files = get_changed_files(context["repo"], context["pr_number"])

    if not changed_files:
        logger.warning("No changed files discovered; producing empty review.")

    # Load actual file contents from workspace
    workspace = os.getenv("GITHUB_WORKSPACE", os.getcwd())
    file_contents = load_file_contents(changed_files, workspace)

    if not file_contents and changed_files:
        logger.warning("Changed files discovered but no content could be loaded.")

    pr_content = PRContent.from_dict(file_contents)

    provider = resolve_provider()
    analysis = analyse(pr_content, provider=provider)

    decision, risk_score = derive_decision_and_risk(analysis.findings)

    # ScanResult requires pr_number >= 1.  When running outside a PR
    # context (e.g. locally or in a non-PR workflow), use 1 as a safe
    # fallback so the structured output is always valid.  Downstream
    # consumers should not treat pr_number=1 as meaningful when the
    # repo is "unknown/unknown" — this is a known Phase 1 pattern.
    pr_number = context["pr_number"] if context["pr_number"] >= 1 else 1

    result = ScanResult(
        repo=context["repo"],
        pr_number=pr_number,
        commit_sha=context["commit_sha"],
        ref=context["ref"],
        decision=decision,
        risk_score=risk_score,
        findings=analysis.findings,
    )

    # Emit structured JSON to stdout (core contract).
    print(result.model_dump_json(indent=2))

    # Generate and emit markdown summary.
    markdown = format_markdown(
        result, concerns=analysis.concerns, observations=analysis.observations,
        provider_notes=analysis.provider_notes,
    )
    print("\n--- Markdown Summary ---\n")
    print(markdown)

    # Surface results in GitHub
    summary_written = write_job_summary(markdown)
    if summary_written:
        logger.info("Wrote review to GitHub job summary.")

    comment_posted = post_pr_comment(context["repo"], context["pr_number"], markdown)
    if comment_posted:
        logger.info("Posted/updated PR comment.")
    elif context["pr_number"] > 0:
        logger.info("PR comment not posted (token may lack permissions or not in PR context).")

    # Optionally send results to the backend ingest API
    _send_to_backend(result)


def mock_run() -> dict:
    """Execute a mock reviewer workflow through the real engine.

    Provides synthetic file contents containing insecure configuration
    patterns and runs them through the full reviewer path:

      mock file contents → engine → checks + reasoning → derive scoring
      → ScanResult → markdown → JSON

    Returns a dict with ``result`` (ScanResult), ``markdown`` (str),
    ``json`` (str), and ``reasoning_notes`` (list[str]) keys.
    """
    # -- Mock PR context --
    mock_context = {
        "repo": "acme/webapp",
        "pr_number": 42,
        "commit_sha": "abc1234def5",
        "ref": "feature/new-endpoint",
    }

    # -- Mock file contents with realistic insecure patterns --
    mock_file_contents: dict[str, str] = {
        "src/settings.py": (
            "# Application settings\n"
            "APP_NAME = 'webapp'\n"
            "DEBUG = True\n"
            "SECRET_KEY = 'change-me'\n"
        ),
        "src/server.py": (
            "from fastapi import FastAPI\n"
            "from fastapi.middleware.cors import CORSMiddleware\n"
            "\n"
            "app = FastAPI()\n"
            'app.add_middleware(CORSMiddleware, allow_origins=["*"])\n'
        ),
        "src/config.py": (
            "# HTTP client configuration\n"
            "VERIFY_SSL = False\n"
            "TIMEOUT = 30\n"
        ),
        "src/routes/admin.py": (
            "from fastapi import APIRouter\n"
            "\n"
            "router = APIRouter()\n"
            "\n"
            "@router.get('/admin/dashboard')\n"
            "async def dashboard():\n"
            "    return {'status': 'ok'}\n"
        ),
        "src/deploy.py": (
            "# Deployment helper\n"
            "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n"
            "AWS_REGION = 'us-east-1'\n"
        ),
    }

    pr_content = PRContent.from_dict(mock_file_contents)

    # -- Run through the real engine --
    analysis = analyse(pr_content)
    decision, risk_score = derive_decision_and_risk(analysis.findings)

    result = ScanResult(
        repo=mock_context["repo"],
        pr_number=mock_context["pr_number"],
        commit_sha=mock_context["commit_sha"],
        ref=mock_context["ref"],
        decision=decision,
        risk_score=risk_score,
        findings=analysis.findings,
    )

    markdown = format_markdown(
        result, concerns=analysis.concerns, observations=analysis.observations,
        provider_notes=analysis.provider_notes,
    )
    json_output = result.model_dump_json(indent=2)

    return {
        "result": result,
        "markdown": markdown,
        "json": json_output,
        "reasoning_notes": analysis.reasoning_notes,
        "concerns": analysis.concerns,
        "observations": analysis.observations,
        "provider_notes": analysis.provider_notes,
    }


def _send_to_backend(result: ScanResult) -> bool:
    """Optionally POST the ScanResult to the backend ingest API.

    Reads ``PARITY_ZERO_API_URL`` and ``PARITY_ZERO_API_TOKEN`` from the
    environment.  If either is absent, ingest is silently skipped.

    On failure, logs a warning but never crashes the action — the reviewer
    run is considered successful regardless of backend availability.

    Returns:
        True if the result was successfully sent, False otherwise.
    """
    api_url = os.getenv("PARITY_ZERO_API_URL", "").rstrip("/")
    api_token = os.getenv("PARITY_ZERO_API_TOKEN", "")

    if not api_url:
        logger.info("PARITY_ZERO_API_URL not set; skipping backend ingest.")
        return False

    if not api_token:
        logger.warning("PARITY_ZERO_API_TOKEN not set; skipping backend ingest.")
        return False

    ingest_url = f"{api_url}/ingest"
    payload = result.model_dump_json()

    req = urllib.request.Request(
        ingest_url,
        data=payload.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status_code = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
        logger.info(
            "Backend ingest succeeded (HTTP %d): %s -> %s",
            status_code, result.scan_id, ingest_url,
        )
        return True
    except urllib.error.HTTPError as exc:
        logger.warning(
            "Backend ingest failed (HTTP %d): %s -> %s",
            exc.code, result.scan_id, ingest_url,
        )
        return False
    except (urllib.error.URLError, OSError) as exc:
        logger.warning(
            "Backend ingest failed (network error): %s -> %s: %s",
            result.scan_id, ingest_url, exc,
        )
        return False


if __name__ == "__main__":
    run()
