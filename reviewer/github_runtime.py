"""GitHub Actions runtime helpers for parity-zero.

Provides functions for discovering changed files, loading file contents,
and surfacing reviewer output in GitHub-native ways (job summary, PR comments).

These helpers are designed for the GitHub Actions environment but degrade
safely when run outside of it.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# Signature marker for parity-zero PR comments — used to find and update
# existing comments instead of posting duplicates.
_COMMENT_MARKER = "<!-- parity-zero-review -->"

# Maximum file size to load (1 MB).  Larger files are skipped.
_MAX_FILE_SIZE = 1_048_576


def discover_changed_files(event_payload: dict) -> list[str]:
    """Discover files changed in the pull request using git diff.

    Uses the PR base SHA from the GitHub event payload to run
    ``git diff --name-only --diff-filter=ACMR`` against HEAD.

    Args:
        event_payload: Parsed GitHub Actions event payload.

    Returns:
        List of repo-relative file paths for added, copied, modified,
        or renamed files.  Returns an empty list if discovery fails.
    """
    pr = event_payload.get("pull_request") or {}
    base_sha = pr.get("base", {}).get("sha", "")
    base_ref = pr.get("base", {}).get("ref", "")

    # Determine the base ref to diff against
    diff_base = ""
    if base_sha:
        diff_base = base_sha
    elif base_ref:
        diff_base = f"origin/{base_ref}"

    if not diff_base:
        logger.info("No PR base ref available for git diff.")
        return []

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", diff_base, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "git diff failed (rc=%d): %s", result.returncode, result.stderr.strip()
            )
            return []

        files = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        logger.info("Discovered %d changed files via git diff against %s.", len(files), diff_base)
        return files

    except FileNotFoundError:
        logger.warning("git not found; cannot discover changed files via diff.")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("git diff timed out.")
        return []
    except Exception as exc:
        logger.warning("Unexpected error during git diff: %s", exc)
        return []


def load_file_contents(
    file_paths: list[str],
    workspace: str | None = None,
) -> dict[str, str]:
    """Load file contents from the workspace for the given paths.

    Reads each file from ``workspace/path``.  Skips files that are
    missing, unreadable, binary, or too large (> 1 MB).

    Args:
        file_paths: Repo-relative file paths to load.
        workspace: Workspace root directory.  Defaults to
            ``GITHUB_WORKSPACE`` or the current working directory.

    Returns:
        A ``{path: content}`` dict for successfully loaded files.
    """
    if workspace is None:
        workspace = os.getenv("GITHUB_WORKSPACE", os.getcwd())

    contents: dict[str, str] = {}
    for path in file_paths:
        full_path = os.path.join(workspace, path)

        if not os.path.isfile(full_path):
            logger.debug("Skipping %s: file does not exist (likely deleted).", path)
            continue

        try:
            size = os.path.getsize(full_path)
        except OSError:
            logger.debug("Skipping %s: cannot stat file.", path)
            continue

        if size > _MAX_FILE_SIZE:
            logger.info("Skipping %s: file too large (%d bytes).", path, size)
            continue

        try:
            with open(full_path, "rb") as fh:
                raw = fh.read()
        except (OSError, IOError) as exc:
            logger.debug("Skipping %s: read error: %s", path, exc)
            continue

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            logger.debug("Skipping %s: binary file.", path)
            continue

        contents[path] = text

    loaded = len(contents)
    skipped = len(file_paths) - loaded
    logger.info("Loaded %d file(s), skipped %d.", loaded, skipped)
    return contents


def write_job_summary(markdown: str) -> bool:
    """Write markdown to the GitHub Actions job summary.

    Appends to the file specified by ``GITHUB_STEP_SUMMARY``.

    Args:
        markdown: Markdown content to write.

    Returns:
        True if the summary was written, False if the env var is not set
        or an I/O error occurred.
    """
    summary_path = os.getenv("GITHUB_STEP_SUMMARY", "")
    if not summary_path:
        logger.debug("GITHUB_STEP_SUMMARY not set; skipping job summary.")
        return False

    try:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(markdown)
            fh.write("\n")
        return True
    except (OSError, IOError) as exc:
        logger.warning("Failed to write job summary: %s", exc)
        return False


def post_pr_comment(repo: str, pr_number: int, markdown: str) -> bool:
    """Post or update a parity-zero review comment on the pull request.

    Uses the GitHub REST API to post a new comment or update an existing
    one identified by the ``<!-- parity-zero-review -->`` marker.

    Args:
        repo: Owner/repo string (e.g. ``"acme/webapp"``).
        pr_number: Pull request number.
        markdown: Markdown content for the comment body.

    Returns:
        True if the comment was posted/updated, False on failure or
        if prerequisites (token, repo, PR number) are missing.
    """
    if not repo or repo == "unknown/unknown" or pr_number < 1:
        logger.debug("Insufficient context for PR comment.")
        return False

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        logger.debug("GITHUB_TOKEN not set; skipping PR comment.")
        return False

    api_url = os.getenv("GITHUB_API_URL", "https://api.github.com")
    body = f"{_COMMENT_MARKER}\n{markdown}"

    # Try to find an existing parity-zero comment to update
    existing_comment_id = _find_existing_comment(api_url, repo, pr_number, token)

    if existing_comment_id:
        return _update_comment(api_url, repo, existing_comment_id, body, token)
    else:
        return _create_comment(api_url, repo, pr_number, body, token)


def _find_existing_comment(
    api_url: str, repo: str, pr_number: int, token: str
) -> int | None:
    """Find an existing parity-zero review comment on the PR.

    Returns the comment ID if found, None otherwise.  Only checks the
    first page of comments (100) to avoid pagination complexity in
    Phase 1.  PRs with more than 100 comments may get a duplicate
    review comment.  A future improvement could iterate through
    paginated results.
    """
    url = f"{api_url}/repos/{repo}/issues/{pr_number}/comments?per_page=100"
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
            comments = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        logger.debug("Could not list PR comments: %s", exc)
        return None

    if not isinstance(comments, list):
        return None

    for comment in comments:
        body = comment.get("body", "")
        if _COMMENT_MARKER in body:
            return comment.get("id")

    return None


def _create_comment(
    api_url: str, repo: str, pr_number: int, body: str, token: str
) -> bool:
    """Create a new PR comment."""
    url = f"{api_url}/repos/{repo}/issues/{pr_number}/comments"
    payload = json.dumps({"body": body}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status in (200, 201):
                logger.info("Created PR comment on %s#%d.", repo, pr_number)
                return True
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        logger.warning("Failed to create PR comment: %s", exc)

    return False


def _update_comment(
    api_url: str, repo: str, comment_id: int, body: str, token: str
) -> bool:
    """Update an existing PR comment."""
    url = f"{api_url}/repos/{repo}/issues/comments/{comment_id}"
    payload = json.dumps({"body": body}).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="PATCH",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                logger.info("Updated existing PR comment %d on %s.", comment_id, repo)
                return True
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        logger.warning("Failed to update PR comment: %s", exc)

    return False
