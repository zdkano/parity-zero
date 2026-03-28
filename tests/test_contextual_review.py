"""Tests for baseline-aware and memory-aware contextual review behavior.

Proves that repository context and review memory now materially influence
review behavior — the core product change for this milestone.

Covers:
A. Canonical context usage (PullRequestContext as preferred engine input)
B. Baseline-aware contextual review (sensitive paths, auth areas, frameworks)
C. Memory-aware contextual review (relevant vs. irrelevant memory)
D. Existing flow stability (ScanResult, markdown, JSON serialization)
E. No overclaiming (notes are informative, not high-confidence findings)
"""

import json

from reviewer.engine import analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.reasoning import (
    ReasoningResult,
    run_reasoning,
    _sensitive_path_overlap,
    _auth_path_overlap,
    _infer_path_categories,
    _relevant_memory_entries,
)
from reviewer.models import (
    PRContent,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)
from schemas.findings import Decision, ScanResult


# ======================================================================
# Helpers
# ======================================================================

def _profile(
    repo: str = "acme/webapp",
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    sensitive_paths: list[str] | None = None,
    auth_patterns: list[str] | None = None,
) -> RepoSecurityProfile:
    """Create a RepoSecurityProfile with overrideable defaults."""
    return RepoSecurityProfile(
        repo=repo,
        languages=languages or [],
        frameworks=frameworks or [],
        sensitive_paths=sensitive_paths or [],
        auth_patterns=auth_patterns or [],
    )


def _memory(*entries: tuple[str, str]) -> ReviewMemory:
    """Create a ReviewMemory from (category, summary) pairs."""
    return ReviewMemory(
        repo="acme/webapp",
        entries=[
            ReviewMemoryEntry(category=cat, summary=summary)
            for cat, summary in entries
        ],
    )


def _ctx(
    files: dict[str, str],
    profile: RepoSecurityProfile | None = None,
    memory: ReviewMemory | None = None,
) -> PullRequestContext:
    """Create a PullRequestContext with convenience defaults."""
    return PullRequestContext(
        pr_content=PRContent.from_dict(files),
        baseline_profile=profile,
        memory=memory,
    )


# ======================================================================
# A. Canonical context usage
# ======================================================================


class TestCanonicalContextUsage:
    """PullRequestContext is the preferred engine input."""

    def test_engine_accepts_pull_request_context_as_canonical(self):
        ctx = _ctx({"src/app.py": "x = 1"})
        result = analyse(ctx)
        assert isinstance(result.findings, list)
        assert isinstance(result.reasoning_notes, list)

    def test_engine_accepts_pr_content_for_compat(self):
        pr = PRContent.from_dict({"src/app.py": "x = 1"})
        result = analyse(pr)
        assert isinstance(result.findings, list)

    def test_engine_accepts_dict_for_compat(self):
        result = analyse({"src/app.py": "x = 1"})
        assert isinstance(result.findings, list)

    def test_reasoning_accepts_pull_request_context(self):
        ctx = _ctx({"src/app.py": "x = 1"})
        result = run_reasoning(ctx)
        assert isinstance(result, ReasoningResult)
        assert len(result.notes) >= 1

    def test_reasoning_accepts_dict_for_backward_compat(self):
        result = run_reasoning({"src/app.py": "x = 1"})
        assert isinstance(result, ReasoningResult)
        assert len(result.notes) >= 1

    def test_context_with_baseline_flows_through_engine(self):
        profile = _profile(
            sensitive_paths=["src/auth/login.py"],
            auth_patterns=["JWT usage detected"],
        )
        ctx = _ctx(
            {"src/auth/login.py": "def login(): pass"},
            profile=profile,
        )
        result = analyse(ctx)
        # The engine should produce baseline-aware contextual notes
        assert any("sensitive" in n.lower() for n in result.reasoning_notes)

    def test_context_with_memory_flows_through_engine(self):
        mem = _memory(("authentication", "Recurring auth bypass concern in login module"))
        ctx = _ctx(
            {"src/auth/handler.py": "def handle(): pass"},
            memory=mem,
        )
        result = analyse(ctx)
        # Memory-aware notes should appear
        assert any("memory" in n.lower() or "prior" in n.lower()
                    for n in result.reasoning_notes)


# ======================================================================
# B. Baseline-aware contextual review
# ======================================================================


class TestBaselineAwareSensitivePaths:
    """PR touching sensitive paths produces relevant contextual notes."""

    def test_sensitive_path_noted(self):
        profile = _profile(sensitive_paths=["src/auth/login.py"])
        ctx = _ctx(
            {"src/auth/login.py": "def login(): pass"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert any("sensitive" in n.lower() for n in result.notes)
        assert any("src/auth/login.py" in n for n in result.notes)

    def test_multiple_sensitive_paths(self):
        profile = _profile(sensitive_paths=[
            "config/settings.py",
            "src/auth/login.py",
        ])
        ctx = _ctx(
            {
                "config/settings.py": "SECRET = 'x'",
                "src/auth/login.py": "def login(): pass",
            },
            profile=profile,
        )
        result = run_reasoning(ctx)
        sensitive_notes = [n for n in result.notes if "sensitive" in n.lower()]
        assert len(sensitive_notes) >= 1

    def test_segment_based_sensitive_match(self):
        """Changed paths with sensitive segments are detected even without
        exact baseline match."""
        profile = _profile()  # no explicit sensitive_paths
        ctx = _ctx(
            {"admin/panel.py": "def admin_view(): pass"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        # 'admin' is a sensitive segment, should trigger a note
        assert any("sensitive" in n.lower() for n in result.notes)

    def test_non_sensitive_path_no_note(self):
        """PR not touching sensitive areas should not produce sensitivity notes."""
        profile = _profile(sensitive_paths=["src/auth/login.py"])
        ctx = _ctx(
            {"src/utils/helpers.py": "def add(a, b): return a + b"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert not any("sensitive" in n.lower() for n in result.notes)


class TestBaselineAwareAuthPaths:
    """PR touching auth-related areas produces relevant contextual notes."""

    def test_auth_path_noted(self):
        profile = _profile(auth_patterns=["JWT usage detected"])
        ctx = _ctx(
            {"src/auth/handler.py": "import jwt"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert any("auth" in n.lower() for n in result.notes)

    def test_login_path_noted(self):
        profile = _profile()
        ctx = _ctx(
            {"login/views.py": "def login(): pass"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        auth_notes = [n for n in result.notes
                      if "authentication" in n.lower() or "authorisation" in n.lower()]
        assert len(auth_notes) >= 1

    def test_oauth_path_noted(self):
        profile = _profile()
        ctx = _ctx(
            {"src/oauth/callback.py": "def callback(): pass"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert any("auth" in n.lower() for n in result.notes)

    def test_non_auth_path_no_auth_note(self):
        """Files in non-auth paths should not produce auth-specific notes."""
        profile = _profile()
        ctx = _ctx(
            {"src/utils/math.py": "def add(a, b): return a + b"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert not any("authentication" in n.lower() or "authorisation" in n.lower()
                        for n in result.notes)


class TestBaselineAwareAuthPatterns:
    """Baseline auth patterns produce contextual notes."""

    def test_auth_patterns_surfaced(self):
        profile = _profile(auth_patterns=[
            "JWT usage detected",
            "OAuth reference detected",
        ])
        ctx = _ctx(
            {"src/app.py": "x = 1"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        auth_notes = [n for n in result.notes if "auth" in n.lower()]
        assert len(auth_notes) >= 1
        assert any("JWT" in n for n in result.notes)

    def test_no_auth_patterns_no_note(self):
        profile = _profile(auth_patterns=[])
        ctx = _ctx(
            {"src/app.py": "x = 1"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert not any("auth-related patterns" in n.lower() for n in result.notes)


class TestBaselineAwareFrameworks:
    """Framework context influences contextual commentary."""

    def test_framework_context_noted(self):
        profile = _profile(frameworks=["fastapi", "sqlalchemy"])
        ctx = _ctx(
            {"src/app.py": "from fastapi import FastAPI"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        framework_notes = [n for n in result.notes if "fastapi" in n.lower()]
        assert len(framework_notes) >= 1

    def test_no_frameworks_no_framework_note(self):
        profile = _profile(frameworks=[])
        ctx = _ctx(
            {"src/app.py": "x = 1"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert not any("framework" in n.lower() for n in result.notes)


class TestBaselineAwareLanguages:
    """Multi-language context produces relevant notes."""

    def test_multi_language_noted(self):
        profile = _profile(languages=["python", "javascript", "go"])
        ctx = _ctx(
            {"src/app.py": "x = 1"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert any("multi-language" in n.lower() for n in result.notes)

    def test_single_language_no_multi_note(self):
        profile = _profile(languages=["python"])
        ctx = _ctx(
            {"src/app.py": "x = 1"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        assert not any("multi-language" in n.lower() for n in result.notes)


class TestNoBaselineMinimalNotes:
    """Without a baseline, no baseline-specific notes are produced."""

    def test_no_baseline_no_sensitive_notes(self):
        ctx = _ctx({"src/auth/login.py": "def login(): pass"})
        result = run_reasoning(ctx)
        assert not any("sensitive" in n.lower() for n in result.notes)

    def test_no_baseline_still_produces_file_count_note(self):
        ctx = _ctx({"src/app.py": "x = 1"})
        result = run_reasoning(ctx)
        assert any("1 file(s)" in n for n in result.notes)


# ======================================================================
# C. Memory-aware contextual review
# ======================================================================


class TestMemoryAwareReview:
    """Review memory influences contextual notes when relevant."""

    def test_relevant_memory_surfaced(self):
        mem = _memory(
            ("authentication", "Recurring concern: auth bypass in login flow"),
        )
        ctx = _ctx(
            {"src/auth/login.py": "def login(): pass"},
            memory=mem,
        )
        result = run_reasoning(ctx)
        assert any("prior" in n.lower() or "recurring" in n.lower()
                    for n in result.notes)

    def test_relevant_memory_entry_content_surfaced(self):
        mem = _memory(
            ("authentication", "Auth bypass found in previous review"),
        )
        ctx = _ctx(
            {"src/auth/handler.py": "def handle(): pass"},
            memory=mem,
        )
        result = run_reasoning(ctx)
        assert any("Auth bypass" in n for n in result.notes)

    def test_unrelated_memory_not_surfaced(self):
        """Memory about dependency_risk should not appear for auth-area changes."""
        mem = _memory(
            ("dependency_risk", "Outdated npm packages in frontend"),
        )
        ctx = _ctx(
            {"src/auth/login.py": "def login(): pass"},
            memory=mem,
        )
        result = run_reasoning(ctx)
        assert not any("npm" in n.lower() for n in result.notes)
        assert not any("dependency" in n.lower() for n in result.notes)

    def test_config_memory_relevant_to_config_paths(self):
        mem = _memory(
            ("insecure_configuration", "Debug mode left enabled in staging config"),
        )
        ctx = _ctx(
            {"config/settings.py": "DEBUG = True"},
            memory=mem,
        )
        result = run_reasoning(ctx)
        assert any("insecure_configuration" in n.lower() or "debug" in n.lower()
                    for n in result.notes)

    def test_empty_memory_no_memory_notes(self):
        mem = ReviewMemory(repo="acme/webapp", entries=[])
        ctx = _ctx(
            {"src/app.py": "x = 1"},
            memory=mem,
        )
        result = run_reasoning(ctx)
        assert not any("memory" in n.lower() or "prior" in n.lower()
                        for n in result.notes)

    def test_no_memory_no_memory_notes(self):
        ctx = _ctx({"src/app.py": "x = 1"})
        result = run_reasoning(ctx)
        assert not any("memory" in n.lower() or "prior" in n.lower()
                        for n in result.notes)

    def test_memory_entries_limited_to_avoid_noise(self):
        """Even with many relevant entries, notes should be bounded."""
        mem = _memory(
            *[("authentication", f"Auth concern #{i}") for i in range(10)]
        )
        ctx = _ctx(
            {"src/auth/login.py": "def login(): pass"},
            memory=mem,
        )
        result = run_reasoning(ctx)
        # Should not dump all 10 entries
        prior_notes = [n for n in result.notes if "Auth concern" in n]
        assert len(prior_notes) <= 3


# ======================================================================
# D. Existing flow stability
# ======================================================================


class TestFlowStability:
    """Verify the end-to-end flow remains stable with contextual review."""

    def test_scan_result_generation(self):
        ctx = _ctx(
            {"config.py": "DEBUG = True\n"},
            profile=_profile(frameworks=["fastapi"]),
        )
        analysis = analyse(ctx)
        decision, risk_score = derive_decision_and_risk(analysis.findings)
        result = ScanResult(
            repo="acme/webapp",
            pr_number=42,
            commit_sha="abc1234def5",
            ref="feature/new",
            decision=decision,
            risk_score=risk_score,
            findings=analysis.findings,
        )
        assert isinstance(result, ScanResult)
        assert len(result.findings) >= 1

    def test_markdown_renders_with_context(self):
        ctx = _ctx(
            {"config.py": "DEBUG = True\n"},
            profile=_profile(frameworks=["fastapi"]),
        )
        analysis = analyse(ctx)
        decision, risk_score = derive_decision_and_risk(analysis.findings)
        result = ScanResult(
            repo="acme/webapp",
            pr_number=42,
            commit_sha="abc1234def5",
            ref="feature/new",
            decision=decision,
            risk_score=risk_score,
            findings=analysis.findings,
        )
        md = format_markdown(result)
        assert "parity-zero Security Review" in md
        assert "Decision:" in md

    def test_json_serialization_stable(self):
        ctx = _ctx({"config.py": "DEBUG = True\n"})
        analysis = analyse(ctx)
        decision, risk_score = derive_decision_and_risk(analysis.findings)
        result = ScanResult(
            repo="acme/webapp",
            pr_number=42,
            commit_sha="abc1234def5",
            ref="feature/new",
            decision=decision,
            risk_score=risk_score,
            findings=analysis.findings,
        )
        json_str = result.model_dump_json()
        parsed = json.loads(json_str)
        assert "scan_id" in parsed
        assert "findings" in parsed
        assert "decision" in parsed
        assert "risk_score" in parsed

    def test_json_round_trip(self):
        ctx = _ctx({"config.py": "VERIFY_SSL = False\n"})
        analysis = analyse(ctx)
        decision, risk_score = derive_decision_and_risk(analysis.findings)
        result = ScanResult(
            repo="acme/webapp",
            pr_number=42,
            commit_sha="abc1234def5",
            ref="feature/new",
            decision=decision,
            risk_score=risk_score,
            findings=analysis.findings,
        )
        restored = ScanResult.model_validate_json(result.model_dump_json())
        assert restored.decision == result.decision
        assert len(restored.findings) == len(result.findings)

    def test_mock_run_still_works(self):
        from reviewer.action import mock_run
        output = mock_run()
        assert isinstance(output["result"], ScanResult)
        assert len(output["result"].findings) > 0
        assert output["result"].decision in (Decision.PASS, Decision.WARN, Decision.BLOCK)
        assert isinstance(output["markdown"], str)
        assert json.loads(output["json"])


# ======================================================================
# E. No overclaiming
# ======================================================================


class TestNoOverclaiming:
    """Contextual notes are informative, not fake high-confidence findings."""

    def test_contextual_notes_do_not_produce_findings(self):
        """Baseline-aware context should produce notes, not findings."""
        profile = _profile(
            sensitive_paths=["src/auth/login.py"],
            auth_patterns=["JWT usage detected"],
            frameworks=["fastapi"],
        )
        mem = _memory(("authentication", "Prior auth concern"))
        ctx = _ctx(
            {"src/auth/login.py": "def login(): pass"},
            profile=profile,
            memory=mem,
        )
        result = run_reasoning(ctx)
        # Notes should exist
        assert len(result.notes) >= 2
        # Findings should remain empty (no fake certainty)
        assert result.findings == []

    def test_notes_are_informative_not_certain(self):
        """Notes should use language of observation, not certainty."""
        profile = _profile(sensitive_paths=["src/auth/login.py"])
        ctx = _ctx(
            {"src/auth/login.py": "def login(): pass"},
            profile=profile,
        )
        result = run_reasoning(ctx)
        # Notes should not claim to have found vulnerabilities
        for note in result.notes:
            assert "vulnerability" not in note.lower()
            assert "critical" not in note.lower()

    def test_engine_findings_come_from_deterministic_only(self):
        """With context, engine findings should still come from deterministic
        checks, not from contextual reasoning (Phase 1)."""
        profile = _profile(
            sensitive_paths=["config/settings.py"],
            frameworks=["fastapi"],
        )
        ctx = _ctx(
            {"config/settings.py": "DEBUG = True\n"},
            profile=profile,
        )
        result = analyse(ctx)
        # Findings should come from deterministic checks
        for finding in result.findings:
            assert finding.category.value in (
                "insecure_configuration", "secrets",
            )
        # Contextual notes should also be present
        assert len(result.reasoning_notes) >= 2


# ======================================================================
# Internal helper tests
# ======================================================================


class TestSensitivePathOverlap:
    """Tests for _sensitive_path_overlap helper."""

    def test_direct_match(self):
        result = _sensitive_path_overlap(
            ["src/auth/login.py"],
            ["src/auth/login.py"],
        )
        assert result == ["src/auth/login.py"]

    def test_segment_match(self):
        result = _sensitive_path_overlap(
            ["admin/views.py"],
            [],
        )
        assert "admin/views.py" in result

    def test_no_match(self):
        result = _sensitive_path_overlap(
            ["src/utils/helpers.py"],
            [],
        )
        assert result == []

    def test_config_segment(self):
        result = _sensitive_path_overlap(
            ["config/db.py"],
            [],
        )
        assert "config/db.py" in result


class TestAuthPathOverlap:
    """Tests for _auth_path_overlap helper."""

    def test_auth_segment(self):
        assert _auth_path_overlap(["src/auth/handler.py"]) == ["src/auth/handler.py"]

    def test_login_segment(self):
        assert _auth_path_overlap(["login/views.py"]) == ["login/views.py"]

    def test_no_auth_segment(self):
        assert _auth_path_overlap(["src/utils/math.py"]) == []


class TestInferPathCategories:
    """Tests for _infer_path_categories helper."""

    def test_auth_path_infers_auth_categories(self):
        cats = _infer_path_categories(["src/auth/login.py"])
        assert "authentication" in cats
        assert "authorization" in cats

    def test_config_path_infers_config_categories(self):
        cats = _infer_path_categories(["config/settings.py"])
        assert "insecure_configuration" in cats
        assert "secrets" in cats

    def test_dependency_file_infers_dependency_risk(self):
        cats = _infer_path_categories(["requirements.txt"])
        assert "dependency_risk" in cats

    def test_clean_path_infers_nothing(self):
        cats = _infer_path_categories(["src/utils/helpers.py"])
        assert len(cats) == 0


class TestRelevantMemoryEntries:
    """Tests for _relevant_memory_entries helper."""

    def test_matching_category(self):
        mem = _memory(("authentication", "Auth concern"))
        entries = _relevant_memory_entries(["src/auth/login.py"], mem)
        assert len(entries) == 1

    def test_non_matching_category(self):
        mem = _memory(("dependency_risk", "NPM concern"))
        entries = _relevant_memory_entries(["src/auth/login.py"], mem)
        assert len(entries) == 0

    def test_empty_memory(self):
        mem = ReviewMemory(repo="acme/webapp")
        entries = _relevant_memory_entries(["src/auth/login.py"], mem)
        assert entries == []
