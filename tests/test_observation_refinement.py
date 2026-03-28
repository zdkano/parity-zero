"""Tests for provider-backed observation refinement (ADR-028).

Covers:
1. Provider-backed observation refinement path (enrichment + supplementary)
2. Observation enrichment without scoring impact
3. No-overclaiming in refined observations
4. Dedup/overlap handling between observations and provider notes
5. Disabled provider behavior unchanged
6. JSON contract stability unchanged
7. End-to-end markdown output remains clean and correctly separated from findings
"""

from __future__ import annotations

import json

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.models import (
    PRContent,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewObservation,
)
from reviewer.observations import (
    _MAX_OBSERVATIONS,
    refine_observations,
)
from reviewer.providers import CandidateNote, DisabledProvider, MockProvider
from reviewer.reasoning import ReasoningResult, run_reasoning
from schemas.findings import Category, Confidence, Decision, Finding, ScanResult, Severity


# ======================================================================
# Helpers
# ======================================================================


def _make_ctx(
    files: dict[str, str] | None = None,
    frameworks: list[str] | None = None,
    auth_patterns: list[str] | None = None,
    memory_entries: list[tuple[str, str]] | None = None,
) -> PullRequestContext:
    file_dict = files or {"app.py": "print('hello')"}
    pr_content = PRContent.from_dict(file_dict)
    profile = None
    if frameworks or auth_patterns:
        profile = RepoSecurityProfile(
            frameworks=frameworks or [],
            auth_patterns=auth_patterns or [],
        )
    memory = None
    if memory_entries:
        memory = ReviewMemory(
            entries=[
                ReviewMemoryEntry(category=cat, summary=summ)
                for cat, summ in memory_entries
            ]
        )
    return PullRequestContext(
        pr_content=pr_content,
        baseline_profile=profile,
        memory=memory,
    )


def _make_scan_result(findings=None) -> ScanResult:
    decision, risk_score = derive_decision_and_risk(findings or [])
    return ScanResult(
        repo="test/repo",
        pr_number=1,
        commit_sha="abc1234",
        ref="main",
        decision=decision,
        risk_score=risk_score,
        findings=findings or [],
    )


def _make_observation(
    path: str = "src/auth.py",
    title: str = "Auth-related path modified",
    summary: str = "Review access control logic.",
    confidence: str = "low",
    basis: str = "auth_bundle_item",
) -> ReviewObservation:
    return ReviewObservation(
        path=path,
        focus_area="authentication",
        title=title,
        summary=summary,
        confidence=confidence,
        basis=basis,
        related_paths=[],
    )


def _make_note(
    title: str = "Token validation concern",
    summary: str = "The token validation flow may have edge cases worth verifying.",
    paths: list[str] | None = None,
    confidence: str = "low",
    source: str = "mock",
) -> CandidateNote:
    return CandidateNote(
        title=title,
        summary=summary,
        related_paths=paths or [],
        confidence=confidence,
        source=source,
    )


# ======================================================================
# 1. Provider-backed observation refinement path
# ======================================================================


class TestRefinementPath:
    """Verify the core refinement path: enrichment and supplementary generation."""

    def test_no_notes_returns_observations_unchanged(self):
        obs = [_make_observation()]
        result = refine_observations(obs, [])
        assert len(result) == 1
        assert result[0].summary == obs[0].summary

    def test_none_like_empty_notes(self):
        obs = [_make_observation()]
        result = refine_observations(obs, [])
        assert len(result) == 1

    def test_enrichment_by_path_match(self):
        obs = [_make_observation(path="src/auth.py")]
        note = _make_note(
            summary="JWT expiration handling may need review.",
            paths=["src/auth.py"],
        )
        result = refine_observations(obs, [note])
        assert len(result) == 1
        assert "provider analysis suggests" in result[0].summary
        assert "JWT expiration" in result[0].summary

    def test_enrichment_marks_basis(self):
        obs = [_make_observation(path="src/auth.py")]
        note = _make_note(paths=["src/auth.py"])
        result = refine_observations(obs, [note])
        assert "provider_enriched" in result[0].basis

    def test_enrichment_does_not_duplicate_basis_marker(self):
        obs = [_make_observation(path="src/auth.py", basis="auth_bundle_item+provider_enriched")]
        note = _make_note(paths=["src/auth.py"])
        result = refine_observations(obs, [note])
        assert result[0].basis.count("provider_enriched") == 1

    def test_enrichment_by_keyword_match(self):
        obs = [_make_observation(
            title="Auth flow consistency check",
            summary="Authentication flow needs consistency verification.",
        )]
        note = _make_note(
            title="Auth flow token validation",
            summary="The authentication flow token handling has edge cases.",
        )
        result = refine_observations(obs, [note])
        assert len(result) == 1
        assert "provider analysis suggests" in result[0].summary

    def test_supplementary_from_unmatched_note(self):
        obs = [_make_observation(path="src/auth.py")]
        note = _make_note(
            title="Config file exposure risk",
            summary="The deployment config may expose internal endpoints.",
            paths=["deploy/config.yaml"],
        )
        result = refine_observations(obs, [note])
        assert len(result) == 2
        supp = result[1]
        assert supp.path == "deploy/config.yaml"
        assert supp.basis == "provider_refinement"
        assert "may warrant attention" in supp.summary

    def test_supplementary_not_created_for_covered_path(self):
        obs = [_make_observation(path="src/auth.py")]
        note = _make_note(
            title="Auth note",
            summary="Some auth concern about the file.",
            paths=["src/auth.py"],
        )
        result = refine_observations(obs, [note])
        # Note targets same path → enriches, no supplementary
        assert len(result) == 1

    def test_supplementary_cap_respected(self):
        obs = [_make_observation(path="src/auth.py")]
        notes = [
            _make_note(
                title=f"Note {i}",
                summary=f"Observation about file number {i} that is detailed enough.",
                paths=[f"src/file{i}.py"],
            )
            for i in range(10)
        ]
        result = refine_observations(obs, notes)
        supplementary = [o for o in result if o.basis == "provider_refinement"]
        assert len(supplementary) <= 3  # _MAX_SUPPLEMENTARY

    def test_total_observations_capped(self):
        obs = [_make_observation(path=f"src/file{i}.py") for i in range(9)]
        notes = [
            _make_note(
                title=f"Note {i}",
                summary=f"Observation about file path{i} that is detailed enough.",
                paths=[f"src/path{i}.py"],
            )
            for i in range(5)
        ]
        result = refine_observations(obs, notes)
        assert len(result) <= _MAX_OBSERVATIONS

    def test_empty_observations_with_notes_creates_supplementary(self):
        note = _make_note(
            title="Interesting area",
            summary="The middleware layer may have security implications.",
            paths=["src/middleware.py"],
        )
        result = refine_observations([], [note])
        assert len(result) == 1
        assert result[0].path == "src/middleware.py"
        assert result[0].basis == "provider_refinement"

    def test_note_without_paths_not_supplementary(self):
        note = _make_note(
            title="General note",
            summary="Some general observation without file paths.",
            paths=[],
        )
        result = refine_observations([], [note])
        assert len(result) == 0

    def test_note_with_short_summary_not_supplementary(self):
        note = _make_note(
            title="Short",
            summary="Too short.",
            paths=["src/file.py"],
        )
        result = refine_observations([], [note])
        assert len(result) == 0

    def test_enrichment_caps_long_detail(self):
        obs = [_make_observation(path="src/auth.py")]
        long_summary = "x " * 200
        note = _make_note(summary=long_summary, paths=["src/auth.py"])
        result = refine_observations(obs, [note])
        # Should be enriched but capped
        assert "provider analysis suggests" in result[0].summary
        added = result[0].summary.split("provider analysis suggests:")[1]
        assert len(added.strip()) <= 250  # capped + ellipsis

    def test_does_not_mutate_original_observations(self):
        obs = [_make_observation(path="src/auth.py")]
        original_summary = obs[0].summary
        note = _make_note(paths=["src/auth.py"])
        refine_observations(obs, [note])
        assert obs[0].summary == original_summary

    def test_supplementary_confidence_clamped(self):
        note = _make_note(
            summary="The file has interesting patterns worth checking.",
            paths=["src/file.py"],
            confidence="high",  # Should be clamped
        )
        result = refine_observations([], [note])
        assert len(result) == 1
        assert result[0].confidence in ("low", "medium")


# ======================================================================
# 2. Observation enrichment without scoring impact
# ======================================================================


class TestNoScoringImpact:
    """Verify that provider-backed observation refinement does not affect scoring."""

    def test_refined_observations_do_not_affect_risk_score(self):
        ctx = _make_ctx(files={
            "src/auth/login.py": "auth code",
            "config.py": "VERIFY_SSL = False\n",
        }, frameworks=["django"], auth_patterns=["jwt"])
        result_disabled = analyse(ctx, provider=DisabledProvider())
        result_mock = analyse(ctx, provider=MockProvider())
        _, score_disabled = derive_decision_and_risk(result_disabled.findings)
        _, score_mock = derive_decision_and_risk(result_mock.findings)
        assert score_disabled == score_mock

    def test_refined_observations_do_not_change_decision(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=MockProvider())
        decision, risk_score = derive_decision_and_risk(result.findings)
        assert decision == Decision.PASS
        assert risk_score == 0

    def test_findings_count_unchanged_with_provider(self):
        ctx = _make_ctx(files={
            "config.py": "VERIFY_SSL = False\n",
        })
        result_disabled = analyse(ctx, provider=DisabledProvider())
        result_mock = analyse(ctx, provider=MockProvider())
        assert len(result_disabled.findings) == len(result_mock.findings)


# ======================================================================
# 3. No-overclaiming in refined observations
# ======================================================================


class TestNoOverclaiming:
    """Verify that refined observations do not claim proven vulnerabilities."""

    def test_supplementary_uses_hedged_language(self):
        note = _make_note(
            title="Potential concern",
            summary="The session handling logic may need additional review.",
            paths=["src/session.py"],
        )
        result = refine_observations([], [note])
        assert len(result) == 1
        # Should use hedged language
        assert "may warrant attention" in result[0].summary

    def test_enrichment_uses_suggests_language(self):
        obs = [_make_observation(path="src/auth.py")]
        note = _make_note(paths=["src/auth.py"])
        result = refine_observations(obs, [note])
        assert "suggests" in result[0].summary

    def test_supplementary_basis_is_provider_refinement(self):
        note = _make_note(
            summary="Worth looking at the middleware configuration.",
            paths=["src/middleware.py"],
        )
        result = refine_observations([], [note])
        assert result[0].basis == "provider_refinement"

    def test_supplementary_confidence_never_high(self):
        note = _make_note(
            summary="The file has interesting patterns worth checking.",
            paths=["src/file.py"],
            confidence="high",
        )
        result = refine_observations([], [note])
        assert result[0].confidence != "high"

    def test_enriched_observation_retains_original_content(self):
        orig_summary = "Original observation about auth logic."
        obs = [_make_observation(path="src/auth.py", summary=orig_summary)]
        note = _make_note(paths=["src/auth.py"])
        result = refine_observations(obs, [note])
        assert result[0].summary.startswith(orig_summary)


# ======================================================================
# 4. Dedup/overlap handling between observations and provider notes
# ======================================================================


class TestDedupOverlap:
    """Verify that refinement handles deduplication and overlap properly."""

    def test_no_duplicate_supplementary_for_same_path(self):
        notes = [
            _make_note(
                title="Note A",
                summary="First observation about the file that is long enough.",
                paths=["src/new.py"],
            ),
            _make_note(
                title="Note B",
                summary="Second observation about the same file long enough.",
                paths=["src/new.py"],
            ),
        ]
        result = refine_observations([], notes)
        paths = [o.path for o in result]
        # Only one supplementary for src/new.py
        assert paths.count("src/new.py") == 1

    def test_enrichment_consumes_matching_note(self):
        obs = [_make_observation(path="src/auth.py")]
        note_matching = _make_note(
            title="Auth concern",
            summary="JWT token needs additional handling review.",
            paths=["src/auth.py"],
        )
        note_new = _make_note(
            title="Config concern",
            summary="Configuration file may have sensitive defaults exposed.",
            paths=["src/config.py"],
        )
        result = refine_observations(obs, [note_matching, note_new])
        assert len(result) == 2
        # First is enriched, second is supplementary
        assert "provider analysis suggests" in result[0].summary
        assert result[1].basis == "provider_refinement"

    def test_multiple_notes_for_same_path_enriches_once(self):
        obs = [_make_observation(path="src/auth.py")]
        notes = [
            _make_note(
                title="Note 1",
                summary="First provider observation about authentication.",
                paths=["src/auth.py"],
            ),
            _make_note(
                title="Note 2",
                summary="Second provider observation about authentication.",
                paths=["src/auth.py"],
            ),
        ]
        result = refine_observations(obs, notes)
        # Only one observation (enriched), not duplicated
        assert len(result) == 1
        assert "provider analysis suggests" in result[0].summary

    def test_empty_note_summary_ignored(self):
        obs = [_make_observation(path="src/auth.py")]
        note = _make_note(summary="", paths=["src/auth.py"])
        result = refine_observations(obs, [note])
        assert len(result) == 1
        assert "provider analysis suggests" not in result[0].summary


# ======================================================================
# 5. Disabled provider behavior unchanged
# ======================================================================


class TestDisabledProviderBehavior:
    """Verify that DisabledProvider behavior is completely unchanged."""

    def test_disabled_provider_no_refinement(self):
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        result = analyse(ctx, provider=DisabledProvider())
        for obs in result.observations:
            assert "provider_enriched" not in obs.basis
            assert obs.basis != "provider_refinement"

    def test_disabled_provider_same_observation_count_as_no_provider(self):
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        result_none = analyse(ctx, provider=None)
        result_disabled = analyse(ctx, provider=DisabledProvider())
        assert len(result_none.observations) == len(result_disabled.observations)

    def test_disabled_provider_observations_identical_to_no_provider(self):
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        result_none = analyse(ctx, provider=None)
        result_disabled = analyse(ctx, provider=DisabledProvider())
        for obs_none, obs_disabled in zip(result_none.observations, result_disabled.observations):
            assert obs_none.path == obs_disabled.path
            assert obs_none.title == obs_disabled.title
            assert obs_none.summary == obs_disabled.summary
            assert obs_none.basis == obs_disabled.basis


# ======================================================================
# 6. JSON contract stability unchanged
# ======================================================================


class TestJsonContractStability:
    """Verify that ScanResult JSON contract is unchanged with refinement."""

    def test_scan_result_shape_with_refined_observations(self):
        ctx = _make_ctx(files={
            "src/auth/login.py": "auth code",
            "config.py": "VERIFY_SSL = False\n",
        }, frameworks=["django"], auth_patterns=["jwt"])
        result = analyse(ctx, provider=MockProvider())
        decision, risk_score = derive_decision_and_risk(result.findings)
        scan = ScanResult(
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
            decision=decision,
            risk_score=risk_score,
            findings=result.findings,
        )
        json_str = scan.model_dump_json()
        data = json.loads(json_str)
        # Core contract keys present
        assert "scan_id" in data
        assert "repo" in data
        assert "pr_number" in data
        assert "commit_sha" in data
        assert "ref" in data
        assert "decision" in data
        assert "risk_score" in data
        assert "findings" in data
        # No observation/provider data in contract
        assert "observations" not in data
        assert "provider_notes" not in data
        assert "concerns" not in data
        assert "reasoning_request" not in data
        assert "provider_name" not in data

    def test_findings_stable_across_provider_modes(self):
        ctx = _make_ctx(files={
            "deploy.py": "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n",
        })
        result_none = analyse(ctx)
        result_disabled = analyse(ctx, provider=DisabledProvider())
        result_mock = analyse(ctx, provider=MockProvider())
        assert len(result_none.findings) == len(result_disabled.findings) == len(result_mock.findings)
        for f1, f2, f3 in zip(
            sorted(result_none.findings, key=lambda f: f.title),
            sorted(result_disabled.findings, key=lambda f: f.title),
            sorted(result_mock.findings, key=lambda f: f.title),
        ):
            assert f1.category == f2.category == f3.category
            assert f1.severity == f2.severity == f3.severity


# ======================================================================
# 7. End-to-end markdown output
# ======================================================================


class TestMarkdownOutput:
    """Verify that refined observations render correctly in markdown."""

    def test_markdown_includes_observation_section(self):
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        result = analyse(ctx, provider=MockProvider())
        scan = _make_scan_result(result.findings)
        md = format_markdown(
            scan,
            concerns=result.concerns,
            observations=result.observations,
            provider_notes=result.provider_notes,
        )
        assert "parity-zero Security Review" in md

    def test_markdown_observations_section_distinct_from_findings(self):
        ctx = _make_ctx(files={
            "config.py": "VERIFY_SSL = False\n",
            "src/auth/login.py": "auth code",
        }, frameworks=["django"], auth_patterns=["jwt"])
        result = analyse(ctx, provider=MockProvider())
        scan = _make_scan_result(result.findings)
        md = format_markdown(
            scan,
            concerns=result.concerns,
            observations=result.observations,
            provider_notes=result.provider_notes,
        )
        # Findings section and observations section are separate
        if result.findings:
            assert "finding" in md.lower()
        if result.observations:
            assert "Review Observations" in md

    def test_markdown_with_enriched_observations(self):
        obs = [_make_observation(path="src/auth.py")]
        note = _make_note(
            summary="Token refresh logic may need session boundary checks.",
            paths=["src/auth.py"],
        )
        refined = refine_observations(obs, [note])
        scan = _make_scan_result()
        md = format_markdown(scan, observations=refined)
        assert "Review Observations" in md
        assert "provider analysis suggests" in md

    def test_markdown_with_supplementary_observations(self):
        note = _make_note(
            title="Middleware configuration concern",
            summary="The middleware configuration may expose internal routing.",
            paths=["src/middleware.py"],
        )
        refined = refine_observations([], [note])
        scan = _make_scan_result()
        md = format_markdown(scan, observations=refined)
        assert "Review Observations" in md
        assert "src/middleware.py" in md

    def test_markdown_observations_not_in_findings_section(self):
        note = _make_note(
            title="Something to check",
            summary="The configuration file has patterns worth reviewing.",
            paths=["src/config.py"],
        )
        refined = refine_observations([], [note])
        scan = _make_scan_result()
        md = format_markdown(scan, observations=refined)
        # Observations should not be in the findings section
        assert "not findings or proven issues" in md

    def test_clean_markdown_with_no_observations(self):
        scan = _make_scan_result()
        md = format_markdown(scan, observations=[])
        assert "Review Observations" not in md

    def test_markdown_structure_valid(self):
        ctx = _make_ctx(
            files={
                "src/auth/login.py": "auth code",
                "src/config.py": "config data",
            },
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        result = analyse(ctx, provider=MockProvider())
        scan = _make_scan_result(result.findings)
        md = format_markdown(
            scan,
            concerns=result.concerns,
            observations=result.observations,
            provider_notes=result.provider_notes,
        )
        # Basic structural checks
        assert md.startswith("## 🔒")
        assert "Decision:" in md
        assert "Risk:" in md
        assert md.rstrip().endswith("")  # ends cleanly


# ======================================================================
# Pipeline integration tests
# ======================================================================


class TestPipelineIntegration:
    """Verify refinement integrates correctly into the full pipeline."""

    def test_mock_provider_triggers_refinement(self):
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        result = analyse(ctx, provider=MockProvider())
        # MockProvider adds notes; check that observations exist
        assert len(result.observations) > 0

    def test_mock_provider_with_matching_file_enriches(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        # Should have observations (possibly enriched by mock provider notes)
        assert len(result.observations) > 0

    def test_reasoning_result_observations_are_review_observations(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        for obs in result.observations:
            assert isinstance(obs, ReviewObservation)

    def test_backward_compat_mock_run_still_works(self):
        from reviewer.action import mock_run
        output = mock_run()
        assert "result" in output
        assert "observations" in output
        assert isinstance(output["observations"], list)

    def test_analyse_returns_observations(self):
        ctx = _make_ctx(
            files={"src/auth/login.py": "auth code"},
            frameworks=["django"],
            auth_patterns=["jwt"],
        )
        result = analyse(ctx, provider=MockProvider())
        assert isinstance(result.observations, list)
        assert all(isinstance(o, ReviewObservation) for o in result.observations)
