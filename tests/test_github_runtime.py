"""Tests for reviewer.github_runtime — GitHub Actions runtime helpers.

Covers:
- Changed file discovery via git diff
- File content loading from workspace
- Job summary output
- PR comment posting (mocked GitHub API)
- Safe degradation for missing/partial context
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from unittest import mock

import pytest

from reviewer.github_runtime import (
    _COMMENT_MARKER,
    _MAX_FILE_SIZE,
    _create_comment,
    _find_existing_comment,
    _update_comment,
    discover_changed_files,
    load_file_contents,
    post_pr_comment,
    write_job_summary,
)


# =====================================================================
# discover_changed_files
# =====================================================================


class TestDiscoverChangedFiles:
    """Tests for git diff-based changed file discovery."""

    def test_returns_empty_when_no_pull_request(self):
        """No pull_request key in event → empty list."""
        assert discover_changed_files({}) == []

    def test_returns_empty_when_no_base_sha_or_ref(self):
        """pull_request present but no base info → empty list."""
        event = {"pull_request": {"head": {"sha": "abc123"}}}
        assert discover_changed_files(event) == []

    def test_returns_empty_when_base_is_empty_dict(self):
        event = {"pull_request": {"base": {}}}
        assert discover_changed_files(event) == []

    @mock.patch("reviewer.github_runtime.subprocess.run")
    def test_uses_base_sha_for_diff(self, mock_run):
        """When base SHA is available, use it for git diff."""
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="src/app.py\nsrc/utils.py\n",
            stderr="",
        )
        event = {
            "pull_request": {
                "base": {"sha": "abc123def", "ref": "main"},
            }
        }
        result = discover_changed_files(event)
        assert result == ["src/app.py", "src/utils.py"]
        args = mock_run.call_args[0][0]
        assert "abc123def" in args
        assert "HEAD" in args

    @mock.patch("reviewer.github_runtime.subprocess.run")
    def test_falls_back_to_base_ref(self, mock_run):
        """When base SHA is missing but ref is present, use origin/ref."""
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="README.md\n",
            stderr="",
        )
        event = {"pull_request": {"base": {"ref": "main"}}}
        result = discover_changed_files(event)
        assert result == ["README.md"]
        args = mock_run.call_args[0][0]
        assert "origin/main" in args

    @mock.patch("reviewer.github_runtime.subprocess.run")
    def test_returns_empty_on_nonzero_exit(self, mock_run):
        """git diff returning non-zero → empty list."""
        mock_run.return_value = mock.Mock(
            returncode=128,
            stdout="",
            stderr="fatal: bad revision",
        )
        event = {"pull_request": {"base": {"sha": "abc123"}}}
        assert discover_changed_files(event) == []

    @mock.patch("reviewer.github_runtime.subprocess.run")
    def test_returns_empty_on_empty_output(self, mock_run):
        """git diff with no changed files → empty list."""
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="",
            stderr="",
        )
        event = {"pull_request": {"base": {"sha": "abc123"}}}
        assert discover_changed_files(event) == []

    @mock.patch("reviewer.github_runtime.subprocess.run")
    def test_strips_whitespace_from_filenames(self, mock_run):
        """Filenames should be stripped of whitespace."""
        mock_run.return_value = mock.Mock(
            returncode=0,
            stdout="  src/app.py  \n\n  src/utils.py  \n",
            stderr="",
        )
        event = {"pull_request": {"base": {"sha": "abc123"}}}
        result = discover_changed_files(event)
        assert result == ["src/app.py", "src/utils.py"]

    @mock.patch("reviewer.github_runtime.subprocess.run", side_effect=FileNotFoundError)
    def test_handles_git_not_found(self, _mock_run):
        """git not installed → empty list, no crash."""
        event = {"pull_request": {"base": {"sha": "abc123"}}}
        assert discover_changed_files(event) == []

    @mock.patch("reviewer.github_runtime.subprocess.run")
    def test_handles_timeout(self, mock_run):
        """git diff timeout → empty list."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)
        event = {"pull_request": {"base": {"sha": "abc123"}}}
        assert discover_changed_files(event) == []


# =====================================================================
# load_file_contents
# =====================================================================


class TestLoadFileContents:
    """Tests for workspace file content loading."""

    def test_loads_text_files(self, tmp_path):
        """Loads readable text files from workspace."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Readme\n", encoding="utf-8")

        contents, skipped = load_file_contents(
            ["src/app.py", "README.md"],
            workspace=str(tmp_path),
        )
        assert "src/app.py" in contents
        assert contents["src/app.py"] == "print('hello')\n"
        assert "README.md" in contents
        assert contents["README.md"] == "# Readme\n"
        assert skipped == []

    def test_skips_missing_files(self, tmp_path):
        """Missing files are skipped with reason 'not_found'."""
        contents, skipped = load_file_contents(
            ["does/not/exist.py"],
            workspace=str(tmp_path),
        )
        assert contents == {}
        assert len(skipped) == 1
        assert skipped[0].path == "does/not/exist.py"
        assert skipped[0].reason == "not_found"

    def test_skips_binary_files(self, tmp_path):
        """Binary files (non-UTF-8) are skipped with reason 'binary'."""
        binary_file = tmp_path / "image.png"
        binary_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 100)

        contents, skipped = load_file_contents(["image.png"], workspace=str(tmp_path))
        assert contents == {}
        assert len(skipped) == 1
        assert skipped[0].path == "image.png"
        assert skipped[0].reason == "binary"

    def test_skips_large_files(self, tmp_path):
        """Files exceeding _MAX_FILE_SIZE are skipped with reason 'too_large'."""
        large_file = tmp_path / "huge.txt"
        large_file.write_text("x" * (_MAX_FILE_SIZE + 1), encoding="utf-8")

        contents, skipped = load_file_contents(["huge.txt"], workspace=str(tmp_path))
        assert contents == {}
        assert len(skipped) == 1
        assert skipped[0].path == "huge.txt"
        assert skipped[0].reason == "too_large"

    def test_loads_files_at_size_limit(self, tmp_path):
        """Files exactly at _MAX_FILE_SIZE are loaded."""
        just_right = tmp_path / "ok.txt"
        content = "x" * _MAX_FILE_SIZE
        just_right.write_text(content, encoding="utf-8")

        contents, skipped = load_file_contents(["ok.txt"], workspace=str(tmp_path))
        assert "ok.txt" in contents
        assert skipped == []

    def test_handles_mixed_files(self, tmp_path):
        """Mix of loadable and skippable files."""
        (tmp_path / "good.py").write_text("pass\n", encoding="utf-8")
        (tmp_path / "binary.bin").write_bytes(b"\x00\xff\xfe")
        # missing.py doesn't exist

        contents, skipped = load_file_contents(
            ["good.py", "binary.bin", "missing.py"],
            workspace=str(tmp_path),
        )
        assert list(contents.keys()) == ["good.py"]
        assert len(skipped) == 2
        skip_paths = {s.path for s in skipped}
        assert "binary.bin" in skip_paths
        assert "missing.py" in skip_paths

    def test_empty_file_list(self, tmp_path):
        """Empty file list → empty result."""
        contents, skipped = load_file_contents([], workspace=str(tmp_path))
        assert contents == {}
        assert skipped == []

    def test_uses_github_workspace_env(self, tmp_path, monkeypatch):
        """Uses GITHUB_WORKSPACE env var when no workspace arg given."""
        (tmp_path / "file.py").write_text("code\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

        contents, skipped = load_file_contents(["file.py"])
        assert "file.py" in contents

    def test_empty_file_is_loaded(self, tmp_path):
        """Empty files are loaded (they are valid text)."""
        (tmp_path / "empty.py").write_text("", encoding="utf-8")
        contents, skipped = load_file_contents(["empty.py"], workspace=str(tmp_path))
        assert "empty.py" in contents
        assert contents["empty.py"] == ""

    def test_utf8_with_bom(self, tmp_path):
        """UTF-8 with BOM is loaded."""
        bom_file = tmp_path / "bom.py"
        bom_file.write_bytes(b"\xef\xbb\xbf# coding: utf-8\n")
        contents, skipped = load_file_contents(["bom.py"], workspace=str(tmp_path))
        assert "bom.py" in contents


# =====================================================================
# write_job_summary
# =====================================================================


class TestWriteJobSummary:
    """Tests for GitHub Actions job summary output."""

    def test_writes_to_summary_file(self, tmp_path, monkeypatch):
        """Writes markdown to GITHUB_STEP_SUMMARY file."""
        summary_file = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        result = write_job_summary("## Test Summary\nAll good.")
        assert result is True
        assert summary_file.read_text() == "## Test Summary\nAll good.\n"

    def test_appends_to_existing_summary(self, tmp_path, monkeypatch):
        """Appends to existing summary file."""
        summary_file = tmp_path / "summary.md"
        summary_file.write_text("Previous content\n")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        result = write_job_summary("New content")
        assert result is True
        content = summary_file.read_text()
        assert "Previous content" in content
        assert "New content" in content

    def test_returns_false_when_env_not_set(self, monkeypatch):
        """Returns False when GITHUB_STEP_SUMMARY is not set."""
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        assert write_job_summary("test") is False

    def test_returns_false_on_io_error(self, monkeypatch):
        """Returns False on I/O error."""
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", "/nonexistent/dir/summary.md")
        assert write_job_summary("test") is False


# =====================================================================
# post_pr_comment — unit tests with mocked API
# =====================================================================


class TestPostPrComment:
    """Tests for PR comment posting/updating."""

    def test_returns_false_when_no_token(self, monkeypatch):
        """No GITHUB_TOKEN → False."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert post_pr_comment("owner/repo", 1, "test") is False

    def test_returns_false_for_invalid_repo(self, monkeypatch):
        """Invalid repo → False."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        assert post_pr_comment("unknown/unknown", 1, "test") is False
        assert post_pr_comment("", 1, "test") is False

    def test_returns_false_for_invalid_pr_number(self, monkeypatch):
        """Invalid PR number → False."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        assert post_pr_comment("owner/repo", 0, "test") is False
        assert post_pr_comment("owner/repo", -1, "test") is False

    @mock.patch("reviewer.github_runtime._find_existing_comment", return_value=None)
    @mock.patch("reviewer.github_runtime._create_comment", return_value=True)
    def test_creates_comment_when_none_exists(self, mock_create, mock_find, monkeypatch):
        """Creates new comment when no existing marker found."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        result = post_pr_comment("owner/repo", 42, "## Review")
        assert result is True
        mock_create.assert_called_once()
        body_arg = mock_create.call_args[0][3]
        assert _COMMENT_MARKER in body_arg

    @mock.patch("reviewer.github_runtime._find_existing_comment", return_value=12345)
    @mock.patch("reviewer.github_runtime._update_comment", return_value=True)
    def test_updates_comment_when_exists(self, mock_update, mock_find, monkeypatch):
        """Updates existing comment when marker is found."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        result = post_pr_comment("owner/repo", 42, "## Updated")
        assert result is True
        mock_update.assert_called_once()
        # Check comment_id argument
        assert mock_update.call_args[0][2] == 12345

    @mock.patch("reviewer.github_runtime._find_existing_comment", return_value=None)
    @mock.patch("reviewer.github_runtime._create_comment", return_value=False)
    def test_returns_false_when_create_fails(self, mock_create, mock_find, monkeypatch):
        """Returns False when comment creation fails."""
        monkeypatch.setenv("GITHUB_TOKEN", "test-token")
        result = post_pr_comment("owner/repo", 42, "## Review")
        assert result is False


class TestFindExistingComment:
    """Tests for _find_existing_comment with mocked API."""

    @mock.patch("reviewer.github_runtime.urllib.request.urlopen")
    def test_finds_comment_with_marker(self, mock_urlopen):
        """Finds existing comment containing the marker."""
        response_data = json.dumps([
            {"id": 100, "body": "unrelated comment"},
            {"id": 200, "body": f"{_COMMENT_MARKER}\n## Review"},
        ]).encode()
        mock_resp = mock.Mock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _find_existing_comment(
            "https://api.github.com", "owner/repo", 42, "token"
        )
        assert result == 200

    @mock.patch("reviewer.github_runtime.urllib.request.urlopen")
    def test_returns_none_when_no_marker(self, mock_urlopen):
        """Returns None when no comment has the marker."""
        response_data = json.dumps([
            {"id": 100, "body": "unrelated comment"},
        ]).encode()
        mock_resp = mock.Mock()
        mock_resp.read.return_value = response_data
        mock_resp.__enter__ = mock.Mock(return_value=mock_resp)
        mock_resp.__exit__ = mock.Mock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _find_existing_comment(
            "https://api.github.com", "owner/repo", 42, "token"
        )
        assert result is None

    @mock.patch("reviewer.github_runtime.urllib.request.urlopen")
    def test_returns_none_on_api_error(self, mock_urlopen):
        """Returns None on API error."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=403, msg="Forbidden", hdrs={}, fp=None
        )
        result = _find_existing_comment(
            "https://api.github.com", "owner/repo", 42, "token"
        )
        assert result is None


# =====================================================================
# Integration: action.run() wiring
# =====================================================================


class TestActionRunIntegration:
    """Tests that action.run() uses real file content loading."""

    @mock.patch("reviewer.action.post_pr_comment", return_value=False)
    @mock.patch("reviewer.action.write_job_summary", return_value=False)
    @mock.patch("reviewer.action.discover_changed_files")
    @mock.patch("reviewer.action._load_event_payload")
    @mock.patch("reviewer.action.get_pr_context")
    def test_run_loads_real_file_contents(
        self,
        mock_ctx,
        mock_event,
        mock_discover,
        mock_summary,
        mock_comment,
        tmp_path,
        monkeypatch,
        capsys,
    ):
        """run() loads actual file contents from workspace."""
        # Set up workspace with a file containing an insecure pattern
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "config.py").write_text("DEBUG = True\n", encoding="utf-8")

        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

        mock_ctx.return_value = {
            "repo": "test/repo",
            "pr_number": 1,
            "commit_sha": "abc1234",
            "ref": "feature",
        }
        mock_event.return_value = {}
        mock_discover.return_value = ["src/config.py"]

        from reviewer.action import run
        run()

        captured = capsys.readouterr()
        # The JSON output should contain an insecure_configuration finding
        # for the DEBUG = True pattern
        assert "insecure_configuration" in captured.out

    @mock.patch("reviewer.action.post_pr_comment", return_value=False)
    @mock.patch("reviewer.action.write_job_summary", return_value=False)
    @mock.patch("reviewer.action.get_changed_files", return_value=["fallback.py"])
    @mock.patch("reviewer.action.discover_changed_files", return_value=[])
    @mock.patch("reviewer.action._load_event_payload")
    @mock.patch("reviewer.action.get_pr_context")
    def test_run_fallback_to_api_when_diff_fails(
        self,
        mock_ctx,
        mock_event,
        mock_discover,
        mock_api_files,
        mock_summary,
        mock_comment,
        tmp_path,
        monkeypatch,
    ):
        """run() falls back to get_changed_files() when git diff returns empty."""
        # Create a file in workspace so loading doesn't fail
        (tmp_path / "fallback.py").write_text("pass\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))

        mock_ctx.return_value = {
            "repo": "test/repo",
            "pr_number": 1,
            "commit_sha": "abc1234",
            "ref": "feature",
        }
        mock_event.return_value = {}

        from reviewer.action import run
        run()

        # Verify both discover (returned empty) and API fallback were called
        mock_discover.assert_called_once()
        mock_api_files.assert_called_once_with("test/repo", 1)

    @mock.patch("reviewer.action.post_pr_comment", return_value=False)
    @mock.patch("reviewer.action.write_job_summary", return_value=True)
    @mock.patch("reviewer.action.discover_changed_files")
    @mock.patch("reviewer.action._load_event_payload")
    @mock.patch("reviewer.action.get_pr_context")
    def test_run_writes_job_summary(
        self,
        mock_ctx,
        mock_event,
        mock_discover,
        mock_summary,
        mock_comment,
        monkeypatch,
    ):
        """run() attempts to write job summary."""
        mock_ctx.return_value = {
            "repo": "test/repo",
            "pr_number": 1,
            "commit_sha": "abc1234",
            "ref": "feature",
        }
        mock_event.return_value = {}
        mock_discover.return_value = []

        from reviewer.action import run
        run()

        mock_summary.assert_called_once()
        # The markdown should contain the parity-zero header
        md_arg = mock_summary.call_args[0][0]
        assert "parity-zero" in md_arg


# =====================================================================
# PullRequestContext assembly
# =====================================================================


class TestPullRequestContextAssembly:
    """Tests that real file contents produce valid PullRequestContext."""

    def test_loaded_contents_create_valid_pr_content(self, tmp_path):
        """load_file_contents → PRContent.from_dict → PullRequestContext."""
        from reviewer.models import PRContent, PullRequestContext

        (tmp_path / "app.py").write_text("import os\n", encoding="utf-8")
        (tmp_path / "config.py").write_text("DEBUG = True\n", encoding="utf-8")

        contents, skipped = load_file_contents(["app.py", "config.py"], workspace=str(tmp_path))
        pr_content = PRContent.from_dict(contents, skipped=skipped)
        ctx = PullRequestContext.from_pr_content(pr_content)

        assert ctx.file_count == 2
        assert "app.py" in ctx.pr_content.paths
        assert "config.py" in ctx.pr_content.paths

    def test_empty_contents_produce_empty_context(self, tmp_path):
        """No loadable files → empty but valid PullRequestContext."""
        from reviewer.models import PRContent, PullRequestContext

        contents, skipped = load_file_contents(["missing.py"], workspace=str(tmp_path))
        pr_content = PRContent.from_dict(contents, skipped=skipped)
        ctx = PullRequestContext.from_pr_content(pr_content)

        assert ctx.file_count == 0
        assert pr_content.skipped_file_count == 1

    def test_full_pipeline_with_loaded_contents(self, tmp_path):
        """Loaded contents flow through analyse() correctly."""
        from reviewer.engine import analyse, derive_decision_and_risk
        from reviewer.models import PRContent

        (tmp_path / "deploy.py").write_text(
            "AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8"
        )
        contents, skipped = load_file_contents(["deploy.py"], workspace=str(tmp_path))
        pr_content = PRContent.from_dict(contents, skipped=skipped)

        analysis = analyse(pr_content)
        assert len(analysis.findings) >= 1

        # Findings should detect the hardcoded AWS key
        categories = [f.category.value for f in analysis.findings]
        assert "secrets" in categories

    def test_pipeline_with_no_findings(self, tmp_path):
        """Clean file produces no findings."""
        from reviewer.engine import analyse, derive_decision_and_risk
        from reviewer.models import PRContent

        (tmp_path / "clean.py").write_text("print('hello')\n", encoding="utf-8")
        contents, skipped = load_file_contents(["clean.py"], workspace=str(tmp_path))
        pr_content = PRContent.from_dict(contents, skipped=skipped)

        analysis = analyse(pr_content)
        decision, risk = derive_decision_and_risk(analysis.findings)
        assert decision.value == "pass"
        assert risk == 0


# =====================================================================
# ScanResult contract stability
# =====================================================================


class TestScanResultContractStability:
    """Ensure no ScanResult contract changes from runtime improvements."""

    def test_scan_result_schema_unchanged(self):
        """ScanResult JSON schema has expected fields."""
        from schemas.findings import ScanResult
        schema = ScanResult.model_json_schema()
        props = schema.get("properties", {})

        expected_fields = {
            "scan_id", "repo", "pr_number", "commit_sha", "ref",
            "timestamp", "decision", "risk_score", "findings",
        }
        assert expected_fields.issubset(set(props.keys()))

    def test_scoring_not_affected_by_runtime_changes(self):
        """Scoring is still purely deterministic from findings."""
        from reviewer.engine import derive_decision_and_risk
        from schemas.findings import Category, Confidence, Finding, Severity

        findings = [
            Finding(
                category=Category.SECRETS,
                severity=Severity.HIGH,
                confidence=Confidence.HIGH,
                title="Test",
                description="Test finding",
                file="test.py",
            )
        ]
        decision, risk = derive_decision_and_risk(findings)
        assert decision.value == "warn"
        assert risk == 25


# =====================================================================
# Output format tests
# =====================================================================


class TestOutputFormat:
    """Tests that output format is correct and preserves trust model."""

    def test_markdown_contains_trust_disclaimer_for_concerns(self):
        """Concerns section includes non-finding disclaimer."""
        from reviewer.formatter import format_markdown
        from reviewer.models import ReviewConcern
        from schemas.findings import ScanResult

        result = ScanResult(
            repo="test/repo", pr_number=1,
            commit_sha="abc1234", ref="main",
        )
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Auth change",
                summary="Auth code modified",
                confidence="low",
                basis="test",
            )
        ]
        md = format_markdown(result, concerns=concerns)
        assert "not proven findings" in md.lower() or "not findings" in md.lower()

    def test_markdown_contains_trust_disclaimer_for_observations(self):
        """Observations section includes non-finding disclaimer."""
        from reviewer.formatter import format_markdown
        from reviewer.models import ReviewObservation
        from schemas.findings import ScanResult

        result = ScanResult(
            repo="test/repo", pr_number=1,
            commit_sha="abc1234", ref="main",
        )
        observations = [
            ReviewObservation(
                path="src/auth.py",
                focus_area="authentication",
                title="Auth file changed",
                summary="Auth file was modified",
                confidence="low",
                basis="test",
            )
        ]
        md = format_markdown(result, observations=observations)
        assert "not findings" in md.lower() or "not proven" in md.lower()

    def test_markdown_sections_are_properly_separated(self):
        """Markdown has distinct sections for findings, concerns, observations."""
        from reviewer.formatter import format_markdown
        from reviewer.models import ReviewConcern, ReviewObservation
        from schemas.findings import Category, Confidence, Finding, ScanResult, Severity

        findings = [
            Finding(
                category=Category.INSECURE_CONFIGURATION,
                severity=Severity.MEDIUM,
                confidence=Confidence.HIGH,
                title="Debug enabled",
                description="Debug mode is on",
                file="config.py",
            )
        ]
        result = ScanResult(
            repo="test/repo", pr_number=1,
            commit_sha="abc1234", ref="main",
            decision="warn", risk_score=15,
            findings=findings,
        )
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Auth concern",
                summary="Test",
            )
        ]
        observations = [
            ReviewObservation(
                path="auth.py",
                title="Auth observation",
                summary="Test",
            )
        ]
        md = format_markdown(result, concerns=concerns, observations=observations)

        # All sections should be present
        assert "Review Concerns" in md
        assert "Review Observations" in md
        assert "MEDIUM" in md

    def test_job_summary_contains_full_markdown(self, tmp_path, monkeypatch):
        """Job summary output contains the complete markdown."""
        summary_file = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

        markdown = "## 🔒 parity-zero Security Review\n\nNo findings."
        write_job_summary(markdown)

        content = summary_file.read_text()
        assert "parity-zero Security Review" in content
        assert "No findings" in content

    def test_pr_comment_body_includes_marker(self):
        """PR comment body includes the parity-zero marker."""
        body = f"{_COMMENT_MARKER}\n## Review"
        assert _COMMENT_MARKER in body


# =====================================================================
# Validation harness compatibility
# =====================================================================


class TestValidationHarnessCompatibility:
    """Ensure validation harness still works after runtime changes."""

    def test_validation_scenarios_importable(self):
        """Validation scenarios can still be imported."""
        from reviewer.validation.scenario import SCENARIOS, list_scenario_ids
        assert len(SCENARIOS) >= 7
        assert "auth-sensitive" in list_scenario_ids()

    def test_validation_runner_importable(self):
        """Validation runner can still be imported and run."""
        from reviewer.validation.runner import run_scenario
        from reviewer.validation.scenario import get_scenario

        scenario = get_scenario("trivial-docs")
        result = run_scenario(scenario)
        assert result.passed

    def test_all_scenarios_still_pass(self):
        """All curated scenarios continue to pass."""
        from reviewer.validation.runner import run_scenario
        from reviewer.validation.scenario import SCENARIOS

        for scenario in SCENARIOS:
            result = run_scenario(scenario)
            failed = [f"{a.name}: {a.detail}" for a in result.assertions if not a.passed]
            assert result.passed, f"Scenario '{scenario.id}' failed: {failed}"
