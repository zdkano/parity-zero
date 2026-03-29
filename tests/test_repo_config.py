"""Tests for repo-level configuration (ADR-041).

Covers:
1. Config loading when file exists
2. No-op behavior when config file is absent
3. Invalid config handling
4. exclude_paths behavior
5. low_signal_paths behavior
6. provider_skip_paths behavior
7. Trust-boundary preservation
8. ScanResult contract unchanged
9. Scoring unchanged
"""

from __future__ import annotations

import os
import textwrap

import pytest

from reviewer.repo_config import (
    RepoConfig,
    filter_excluded_paths,
    load_config,
    load_config_from_text,
    all_provider_skip,
    _matches_any,
)
from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.models import PRContent, PullRequestContext
from schemas.findings import ScanResult


# ======================================================================
# 1. Config loading when file exists
# ======================================================================


class TestConfigLoading:
    def test_load_valid_config(self, tmp_path):
        cfg_file = tmp_path / ".parity-zero.yml"
        cfg_file.write_text(textwrap.dedent("""\
            exclude_paths:
              - "vendor/**"
              - "docs/**"
            low_signal_paths:
              - "tests/**"
            provider_skip_paths:
              - "fixtures/**"
        """))
        config = load_config(str(tmp_path))
        assert config.exclude_paths == ("vendor/**", "docs/**")
        assert config.low_signal_paths == ("tests/**",)
        assert config.provider_skip_paths == ("fixtures/**",)
        assert not config.is_empty

    def test_load_partial_config(self, tmp_path):
        cfg_file = tmp_path / ".parity-zero.yml"
        cfg_file.write_text("exclude_paths:\n  - 'gen/**'\n")
        config = load_config(str(tmp_path))
        assert config.exclude_paths == ("gen/**",)
        assert config.low_signal_paths == ()
        assert config.provider_skip_paths == ()

    def test_load_from_text(self):
        config = load_config_from_text("exclude_paths:\n  - 'a/**'\n")
        assert config.exclude_paths == ("a/**",)

    def test_load_empty_yaml(self, tmp_path):
        (tmp_path / ".parity-zero.yml").write_text("")
        config = load_config(str(tmp_path))
        assert config.is_empty


# ======================================================================
# 2. No-op behavior when config file is absent
# ======================================================================


class TestNoOpWhenAbsent:
    def test_missing_file_returns_empty(self, tmp_path):
        config = load_config(str(tmp_path))
        assert config.is_empty

    def test_empty_config_no_effect(self):
        config = RepoConfig()
        assert not config.is_excluded("src/main.py")
        assert not config.is_low_signal("tests/test_a.py")
        assert not config.is_provider_skip("docs/readme.md")

    def test_analyse_unchanged_without_config(self):
        files = {"src/settings.py": "DEBUG = True\n"}
        result_no_cfg = analyse(files)
        result_empty_cfg = analyse(files, config=RepoConfig())
        assert len(result_no_cfg.findings) == len(result_empty_cfg.findings)


# ======================================================================
# 3. Invalid config handling
# ======================================================================


class TestInvalidConfig:
    def test_non_dict_yaml(self):
        config = load_config_from_text("- item1\n- item2\n")
        assert config.is_empty

    def test_unknown_keys(self):
        config = load_config_from_text("unknown_field: true\n")
        assert config.is_empty

    def test_non_list_paths(self):
        config = load_config_from_text("exclude_paths: 'not-a-list'\n")
        assert config.is_empty

    def test_non_string_path_entry(self):
        config = load_config_from_text("exclude_paths:\n  - 123\n")
        assert config.is_empty

    def test_empty_string_path_entry(self):
        config = load_config_from_text("exclude_paths:\n  - ''\n")
        assert config.is_empty

    def test_malformed_yaml(self, tmp_path):
        (tmp_path / ".parity-zero.yml").write_text(": invalid: yaml: {{{\n")
        config = load_config(str(tmp_path))
        assert config.is_empty


# ======================================================================
# 4. exclude_paths behavior
# ======================================================================


class TestExcludePaths:
    def test_glob_matching(self):
        config = RepoConfig(exclude_paths=("vendor/**", "docs/**", "*.generated.py"))
        assert config.is_excluded("vendor/lib/foo.py")
        assert config.is_excluded("docs/readme.md")
        assert config.is_excluded("src/model.generated.py")
        assert not config.is_excluded("src/main.py")

    def test_filter_excluded_paths(self):
        config = RepoConfig(exclude_paths=("docs/**",))
        contents = {"src/main.py": "code", "docs/readme.md": "text"}
        filtered, excluded = filter_excluded_paths(contents, config)
        assert "src/main.py" in filtered
        assert "docs/readme.md" not in filtered
        assert excluded == ["docs/readme.md"]

    def test_excluded_files_not_analysed(self):
        config = RepoConfig(exclude_paths=("src/settings.py",))
        files = {"src/settings.py": "DEBUG = True\n", "src/other.py": "x = 1\n"}
        result = analyse(files, config=config)
        # The excluded file should not produce findings
        for f in result.findings:
            assert f.file != "src/settings.py"

    def test_excluded_files_tracked_as_skipped(self):
        config = RepoConfig(exclude_paths=("src/settings.py",))
        files = {"src/settings.py": "DEBUG = True\n"}
        pr = PRContent.from_dict(files)
        ctx = PullRequestContext.from_pr_content(pr)
        result = analyse(ctx, config=config)
        # No findings from excluded file
        assert all(f.file != "src/settings.py" for f in result.findings)


# ======================================================================
# 5. low_signal_paths behavior
# ======================================================================


class TestLowSignalPaths:
    def test_low_signal_matching(self):
        config = RepoConfig(low_signal_paths=("tests/**", "*.lock"))
        assert config.is_low_signal("tests/test_foo.py")
        assert config.is_low_signal("package-lock.json") is False  # *.lock not .json
        assert config.is_low_signal("yarn.lock")
        assert not config.is_low_signal("src/main.py")

    def test_low_signal_suppresses_observations(self):
        """Low-signal files should produce fewer/no observations."""
        config = RepoConfig(low_signal_paths=("tests/**",))
        files = {"tests/test_auth.py": "from auth import login\n"}
        ctx = PullRequestContext.from_dict(files)
        result_with = analyse(ctx, config=config)
        result_without = analyse(ctx, config=RepoConfig())
        # With low-signal config, observations for test files should be suppressed
        low_signal_obs = [o for o in result_with.observations if o.path.startswith("tests/")]
        assert len(low_signal_obs) == 0


# ======================================================================
# 6. provider_skip_paths behavior
# ======================================================================


class TestProviderSkipPaths:
    def test_provider_skip_matching(self):
        config = RepoConfig(provider_skip_paths=("docs/**", "fixtures/**"))
        assert config.is_provider_skip("docs/readme.md")
        assert config.is_provider_skip("fixtures/data.json")
        assert not config.is_provider_skip("src/main.py")

    def test_all_provider_skip(self):
        config = RepoConfig(provider_skip_paths=("docs/**",))
        assert all_provider_skip(["docs/a.md", "docs/b.md"], config)
        assert not all_provider_skip(["docs/a.md", "src/b.py"], config)
        assert not all_provider_skip([], config)

    def test_empty_config_all_provider_skip(self):
        assert not all_provider_skip(["docs/a.md"], RepoConfig())


# ======================================================================
# 7. Trust-boundary preservation
# ======================================================================


class TestTrustBoundary:
    def test_config_does_not_create_findings(self):
        """Config should never introduce findings on its own."""
        config = RepoConfig(
            exclude_paths=("vendor/**",),
            low_signal_paths=("tests/**",),
            provider_skip_paths=("docs/**",),
        )
        files = {"src/clean.py": "x = 1\n"}
        result = analyse(files, config=config)
        assert len(result.findings) == 0

    def test_config_does_not_affect_scoring(self):
        """Scoring must derive from findings only, not config."""
        files = {"src/settings.py": "DEBUG = True\n"}
        result = analyse(files, config=RepoConfig())
        decision, risk = derive_decision_and_risk(result.findings)
        # Same files with a config that doesn't exclude them
        config = RepoConfig(low_signal_paths=("unrelated/**",))
        result2 = analyse(files, config=config)
        decision2, risk2 = derive_decision_and_risk(result2.findings)
        assert decision == decision2
        assert risk == risk2


# ======================================================================
# 8. ScanResult contract unchanged
# ======================================================================


class TestScanResultContract:
    def test_scan_result_structure_with_config(self):
        config = RepoConfig(exclude_paths=("vendor/**",))
        files = {"src/settings.py": "DEBUG = True\n"}
        result = analyse(files, config=config)
        decision, risk = derive_decision_and_risk(result.findings)
        scan = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc123",
            ref="main",
            decision=decision,
            risk_score=risk,
            findings=result.findings,
        )
        data = scan.model_dump()
        assert "repo" in data
        assert "findings" in data
        assert "decision" in data
        assert "risk_score" in data


# ======================================================================
# 9. Scoring unchanged
# ======================================================================


class TestScoringUnchanged:
    def test_scoring_same_with_and_without_config(self):
        files = {
            "src/settings.py": "DEBUG = True\n",
            "src/server.py": 'allow_origins=["*"]\n',
        }
        r1 = analyse(files)
        r2 = analyse(files, config=RepoConfig())
        d1, s1 = derive_decision_and_risk(r1.findings)
        d2, s2 = derive_decision_and_risk(r2.findings)
        assert d1 == d2
        assert s1 == s2

    def test_exclude_reduces_findings_not_score_formula(self):
        files = {
            "src/settings.py": "DEBUG = True\n",
            "vendor/lib.py": "DEBUG = True\n",
        }
        config = RepoConfig(exclude_paths=("vendor/**",))
        result = analyse(files, config=config)
        # Only src/settings.py finding should remain
        assert all(f.file != "vendor/lib.py" for f in result.findings)


# ======================================================================
# Path matching edge cases
# ======================================================================


class TestPathMatching:
    def test_nested_glob(self):
        assert _matches_any("a/b/c/d.py", ("a/**",))

    def test_basename_match(self):
        assert _matches_any("deep/path/file.lock", ("*.lock",))

    def test_no_patterns(self):
        assert not _matches_any("anything.py", ())

    def test_exact_match(self):
        assert _matches_any("README.md", ("README.md",))
