"""Tests for provider output quality improvements (ADR-027).

Covers:
1. Improved prompt/request structure
2. CandidateNote normalization
3. Deduplication / overlap suppression behavior
4. Markdown output ordering and condensation
5. No trust-model regression:
   - Provider notes remain non-finding
   - No scoring impact
   - No ScanResult contract change
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.formatter import format_markdown
from reviewer.models import (
    PRContent,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewBundleItem,
    ReviewConcern,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewObservation,
    ReviewPlan,
)
from reviewer.providers import (
    CandidateNote,
    DisabledProvider,
    GitHubModelsProvider,
    MockProvider,
    ReasoningRequest,
    ReasoningResponse,
    _format_user_prompt,
    _parse_candidate_notes,
    _SYSTEM_PROMPT,
)
from reviewer.reasoning import (
    ReasoningResult,
    _extract_keywords,
    _suppress_overlapping_notes,
    run_reasoning,
)
from schemas.findings import (
    Category,
    Confidence,
    Decision,
    Finding,
    ScanResult,
    Severity,
)


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


def _make_finding(
    category: str = "secrets",
    title: str = "Hardcoded secret",
    description: str = "A secret was found in the code",
    file: str = "config.py",
) -> Finding:
    return Finding(
        category=Category(category),
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        title=title,
        description=description,
        file=file,
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


def _mock_httpx_response(content: str, status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    mock_resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_resp,
        )
    return mock_resp


# ======================================================================
# 1. Improved prompt/request structure tests
# ======================================================================


class TestImprovedPromptStructure:
    """Verify prompt improvements steer provider toward better output."""

    def test_system_prompt_discourages_restating_deterministic(self):
        assert "do not" in _SYSTEM_PROMPT.lower() or "NOT" in _SYSTEM_PROMPT
        assert "deterministic" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_file_specificity(self):
        assert "file" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_requires_uncertainty(self):
        prompt_lower = _SYSTEM_PROMPT.lower()
        assert any(word in prompt_lower for word in ["uncertain", "may", "could", "verif"])

    def test_system_prompt_discourages_generic_advice(self):
        prompt_lower = _SYSTEM_PROMPT.lower()
        assert "generic" in prompt_lower

    def test_system_prompt_requests_structured_objects(self):
        assert "title" in _SYSTEM_PROMPT
        assert "summary" in _SYSTEM_PROMPT
        assert "confidence" in _SYSTEM_PROMPT

    def test_user_prompt_marks_already_detected(self):
        req = ReasoningRequest(
            changed_files_summary=[{"path": "a.py", "review_reason": "changed_file", "focus_areas": ""}],
            deterministic_findings_summary=[
                {"category": "secrets", "title": "Hardcoded key", "file": "config.py"},
            ],
        )
        prompt = _format_user_prompt(req)
        assert "ALREADY DETECTED" in prompt
        assert "do not repeat" in prompt.lower() or "NOT" in prompt

    def test_user_prompt_includes_concerns_in_already_detected(self):
        req = ReasoningRequest(
            changed_files_summary=[{"path": "a.py", "review_reason": "changed_file", "focus_areas": ""}],
            existing_concerns=[
                {"category": "auth", "title": "Missing auth", "summary": "No auth check"},
            ],
        )
        prompt = _format_user_prompt(req)
        assert "Missing auth" in prompt
        assert "ALREADY DETECTED" in prompt

    def test_user_prompt_includes_observations_in_already_detected(self):
        req = ReasoningRequest(
            changed_files_summary=[{"path": "a.py", "review_reason": "changed_file", "focus_areas": ""}],
            existing_observations=[
                {"path": "auth.py", "title": "Auth obs", "summary": "Worth reviewing"},
            ],
        )
        prompt = _format_user_prompt(req)
        assert "Auth obs" in prompt
        assert "ALREADY DETECTED" in prompt

    def test_user_prompt_no_already_detected_when_nothing_detected(self):
        req = ReasoningRequest(
            changed_files_summary=[{"path": "a.py", "review_reason": "changed_file", "focus_areas": ""}],
        )
        prompt = _format_user_prompt(req)
        assert "ALREADY DETECTED" not in prompt


# ======================================================================
# 2. CandidateNote normalization tests
# ======================================================================


class TestCandidateNoteNormalization:
    """Verify CandidateNote dataclass and normalization behavior."""

    def test_candidate_note_defaults(self):
        note = CandidateNote()
        assert note.title == ""
        assert note.summary == ""
        assert note.related_paths == []
        assert note.confidence == "low"
        assert note.source == ""

    def test_candidate_note_with_values(self):
        note = CandidateNote(
            title="Auth check missing",
            summary="The /admin endpoint lacks auth middleware",
            related_paths=["routes/admin.py"],
            confidence="medium",
            source="github-models",
        )
        assert note.title == "Auth check missing"
        assert note.summary == "The /admin endpoint lacks auth middleware"
        assert note.related_paths == ["routes/admin.py"]
        assert note.confidence == "medium"
        assert note.source == "github-models"

    def test_parse_structured_objects_normalized(self):
        raw = json.dumps([
            {
                "title": "Auth concern",
                "summary": "Missing middleware on admin endpoint",
                "paths": ["admin.py"],
                "confidence": "medium",
            }
        ])
        notes = _parse_candidate_notes(raw, provider_name="test")
        assert len(notes) == 1
        note = notes[0]
        assert isinstance(note, CandidateNote)
        assert note.title == "Auth concern"
        assert note.summary == "Missing middleware on admin endpoint"
        assert note.related_paths == ["admin.py"]
        assert note.confidence == "medium"
        assert note.source == "test"

    def test_parse_string_array_normalized(self):
        raw = '["Simple observation about auth"]'
        notes = _parse_candidate_notes(raw, provider_name="test")
        assert len(notes) == 1
        note = notes[0]
        assert isinstance(note, CandidateNote)
        assert note.summary == "Simple observation about auth"
        assert note.confidence == "low"
        assert note.source == "test"

    def test_parse_title_derived_from_summary_when_missing(self):
        raw = json.dumps([{"summary": "A detailed observation"}])
        notes = _parse_candidate_notes(raw)
        assert notes[0].title == "A detailed observation"

    def test_parse_summary_derived_from_title_when_missing(self):
        raw = json.dumps([{"title": "Short title only"}])
        notes = _parse_candidate_notes(raw)
        assert notes[0].summary == "Short title only"

    def test_parse_empty_object_skipped(self):
        raw = json.dumps([{}, {"title": "Valid note", "summary": "Detail"}])
        notes = _parse_candidate_notes(raw)
        assert len(notes) == 1

    def test_parse_paths_string_normalized_to_list(self):
        raw = json.dumps([{"title": "Note", "summary": "Detail", "paths": "single.py"}])
        notes = _parse_candidate_notes(raw)
        assert notes[0].related_paths == ["single.py"]

    def test_mock_provider_produces_structured_notes(self):
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[{"path": "a.py", "review_reason": "changed_file", "focus_areas": ""}],
            plan_focus_areas=["authentication"],
        )
        resp = provider.reason(req)
        assert len(resp.structured_notes) > 0
        assert all(isinstance(n, CandidateNote) for n in resp.structured_notes)
        assert resp.structured_notes[0].source == "mock"


# ======================================================================
# 3. Deduplication / overlap suppression tests
# ======================================================================


class TestOverlapSuppression:
    """Verify overlap suppression filters redundant provider notes."""

    def test_empty_notes_returns_empty(self):
        result = _suppress_overlapping_notes([])
        assert result == []

    def test_no_existing_context_keeps_all(self):
        notes = [
            CandidateNote(title="Auth issue", summary="Missing auth check"),
            CandidateNote(title="Config issue", summary="Debug mode enabled"),
        ]
        result = _suppress_overlapping_notes(notes)
        assert len(result) == 2

    def test_overlapping_concern_suppressed(self):
        notes = [
            CandidateNote(
                title="Authentication boundary concern",
                summary="The authentication boundary may be affected by this change",
            ),
        ]
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Authentication boundary concern",
                summary="The authentication boundary may be affected by this change",
            ),
        ]
        result = _suppress_overlapping_notes(notes, concerns=concerns)
        assert len(result) == 0

    def test_overlapping_observation_suppressed(self):
        notes = [
            CandidateNote(
                title="Auth file observation",
                summary="auth.py touches authentication boundary and deserves scrutiny",
            ),
        ]
        observations = [
            ReviewObservation(
                path="auth.py",
                title="Auth file scrutiny",
                summary="auth.py touches authentication boundary and warrants review",
            ),
        ]
        result = _suppress_overlapping_notes(notes, observations=observations)
        assert len(result) == 0

    def test_overlapping_finding_suppressed(self):
        notes = [
            CandidateNote(
                title="Hardcoded secret detected in config",
                summary="A hardcoded secret was found in the config file",
            ),
        ]
        findings = [
            _make_finding(
                title="Hardcoded secret detected in config",
                description="A hardcoded secret was found in the config file",
            ),
        ]
        result = _suppress_overlapping_notes(notes, deterministic_findings=findings)
        assert len(result) == 0

    def test_non_overlapping_notes_kept(self):
        notes = [
            CandidateNote(
                title="CORS configuration concern",
                summary="The CORS middleware allows wildcard origins",
            ),
        ]
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Auth pattern check",
                summary="JWT validation may need review",
            ),
        ]
        result = _suppress_overlapping_notes(notes, concerns=concerns)
        assert len(result) == 1

    def test_mixed_overlap_filters_correctly(self):
        notes = [
            CandidateNote(title="Note A", summary="About authentication boundary patterns"),
            CandidateNote(title="Note B", summary="About CORS wildcard configuration"),
            CandidateNote(title="Note C", summary="About authentication boundary patterns and access"),
        ]
        concerns = [
            ReviewConcern(
                category="authentication",
                title="Auth boundary",
                summary="Authentication boundary patterns need review",
            ),
        ]
        result = _suppress_overlapping_notes(notes, concerns=concerns)
        # Notes A and C overlap heavily with the concern; B should remain
        kept_titles = [n.title for n in result]
        assert "Note B" in kept_titles

    def test_max_notes_capped(self):
        notes = [
            CandidateNote(title=f"Unique note {i}", summary=f"Unique observation number {i}")
            for i in range(20)
        ]
        result = _suppress_overlapping_notes(notes)
        assert len(result) <= 5

    def test_extract_keywords_basic(self):
        keywords = _extract_keywords("The authentication boundary is affected")
        assert "authentication" in keywords
        assert "boundary" in keywords
        assert "affected" in keywords
        # Stopwords removed
        assert "the" not in keywords
        assert "is" not in keywords

    def test_extract_keywords_empty(self):
        assert _extract_keywords("") == set()
        assert _extract_keywords("  ") == set()

    def test_pipeline_integration_with_overlap_suppression(self):
        """Provider notes flow through suppression in the pipeline."""
        from reviewer.planner import build_review_plan

        ctx = _make_ctx(files={"src/auth/login.py": "auth code"})
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        # Provider notes should be available (may be filtered)
        assert isinstance(result.provider_notes, list)
        assert all(isinstance(n, CandidateNote) for n in result.provider_notes)


# ======================================================================
# 4. Markdown output ordering and condensation tests
# ======================================================================


class TestMarkdownOutputQuality:
    """Verify markdown output renders provider notes correctly."""

    def test_provider_notes_section_rendered(self):
        scan = _make_scan_result()
        notes = [
            CandidateNote(
                title="Auth observation",
                summary="The admin endpoint may lack auth checks",
                related_paths=["admin.py"],
                confidence="medium",
            ),
        ]
        md = format_markdown(scan, provider_notes=notes)
        assert "Additional Review Notes" in md
        assert "Auth observation" in md
        assert "admin.py" in md
        assert "medium" in md

    def test_provider_notes_section_absent_when_empty(self):
        scan = _make_scan_result()
        md = format_markdown(scan, provider_notes=[])
        assert "Additional Review Notes" not in md

    def test_provider_notes_section_absent_when_none(self):
        scan = _make_scan_result()
        md = format_markdown(scan, provider_notes=None)
        assert "Additional Review Notes" not in md

    def test_provider_notes_capped_at_five(self):
        scan = _make_scan_result()
        notes = [
            CandidateNote(title=f"Note {i}", summary=f"Observation {i}")
            for i in range(10)
        ]
        md = format_markdown(scan, provider_notes=notes)
        # Count the note entries (each starts with "- **Note")
        note_count = md.count("- **Note")
        assert note_count <= 5

    def test_provider_notes_after_observations(self):
        scan = _make_scan_result()
        observations = [
            ReviewObservation(path="a.py", title="Obs", summary="Detail"),
        ]
        notes = [
            CandidateNote(title="Provider note", summary="Detail"),
        ]
        md = format_markdown(scan, observations=observations, provider_notes=notes)
        obs_pos = md.index("Review Observations")
        notes_pos = md.index("Additional Review Notes")
        assert notes_pos > obs_pos

    def test_findings_before_everything(self):
        findings = [
            _make_finding(title="High severity issue"),
        ]
        scan = _make_scan_result(findings=findings)
        concerns = [
            ReviewConcern(category="auth", title="Concern", summary="Detail"),
        ]
        notes = [
            CandidateNote(title="Provider note", summary="Detail"),
        ]
        md = format_markdown(scan, concerns=concerns, provider_notes=notes)
        # Findings section (HIGH) should come before concerns and notes
        high_pos = md.index("HIGH")
        concern_pos = md.index("Review Concerns")
        notes_pos = md.index("Additional Review Notes")
        assert high_pos < concern_pos < notes_pos

    def test_provider_notes_marked_as_non_authoritative(self):
        scan = _make_scan_result()
        notes = [CandidateNote(title="Note", summary="Detail")]
        md = format_markdown(scan, provider_notes=notes)
        assert "not proven findings" in md.lower() or "may require verification" in md.lower()

    def test_backward_compat_format_markdown_no_provider_notes(self):
        """format_markdown works without provider_notes parameter."""
        scan = _make_scan_result()
        md = format_markdown(scan)
        assert "parity-zero Security Review" in md


# ======================================================================
# 5. Trust model regression tests
# ======================================================================


class TestTrustModelRegression:
    """Verify no trust-model regression from provider output quality changes."""

    def test_provider_notes_are_not_findings(self):
        """Provider notes must never become findings."""
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=MockProvider())
        # Clean file: no findings even with mock provider
        assert len(result.findings) == 0
        # But provider notes may be present
        assert isinstance(result.provider_notes, list)

    @patch("reviewer.providers._httpx_mod")
    def test_live_provider_notes_are_not_findings(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            json.dumps([
                {"title": "Critical vulnerability", "summary": "SQL injection found", "confidence": "medium"},
            ])
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=provider)
        assert len(result.findings) == 0

    def test_no_scoring_impact_from_provider_notes(self):
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        result_default = analyse(ctx)
        result_mock = analyse(ctx, provider=MockProvider())
        _, score_default = derive_decision_and_risk(result_default.findings)
        _, score_mock = derive_decision_and_risk(result_mock.findings)
        assert score_default == score_mock

    @patch("reviewer.providers._httpx_mod")
    def test_no_scoring_impact_from_live_provider(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            json.dumps([
                {"title": "Issue", "summary": "SSL disabled", "paths": ["config.py"]},
            ])
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
        result_provider = analyse(ctx, provider=provider)
        result_default = analyse(ctx)
        _, score_provider = derive_decision_and_risk(result_provider.findings)
        _, score_default = derive_decision_and_risk(result_default.findings)
        assert score_provider == score_default

    def test_scan_result_contract_unchanged(self):
        ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
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
        data = json.loads(scan.model_dump_json())
        # Core contract keys present
        assert "scan_id" in data
        assert "repo" in data
        assert "pr_number" in data
        assert "decision" in data
        assert "risk_score" in data
        assert "findings" in data
        # No provider-specific keys leak
        assert "provider_notes" not in data
        assert "candidate_notes" not in data
        assert "structured_notes" not in data
        assert "CandidateNote" not in json.dumps(data)

    def test_disabled_provider_produces_no_provider_notes(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=DisabledProvider())
        assert result.provider_notes == []

    def test_provider_failure_graceful(self):
        """Pipeline continues normally when provider fails."""
        with patch("reviewer.providers._httpx_mod") as mock_httpx:
            mock_httpx.post.side_effect = Exception("Connection refused")
            provider = GitHubModelsProvider(token="test-token")
            ctx = _make_ctx(files={"config.py": "VERIFY_SSL = False\n"})
            result = analyse(ctx, provider=provider)
            assert isinstance(result, AnalysisResult)
            assert len(result.findings) > 0  # Deterministic findings still work

    def test_mock_run_still_works(self):
        from reviewer.action import mock_run
        output = mock_run()
        assert "result" in output
        assert "markdown" in output
        assert "json" in output
        assert isinstance(output["result"], ScanResult)


# ======================================================================
# 6. Structured notes flow through pipeline
# ======================================================================


class TestStructuredNotesFlow:
    """Verify structured notes flow correctly through the full pipeline."""

    @patch("reviewer.providers._httpx_mod")
    def test_structured_notes_reach_analysis_result(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            json.dumps([
                {"title": "CORS issue", "summary": "Wildcard CORS config", "paths": ["server.py"], "confidence": "medium"},
            ])
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"server.py": "CORS = '*'"})
        result = analyse(ctx, provider=provider)
        # provider_notes should be present (may be filtered by overlap suppression)
        assert isinstance(result.provider_notes, list)

    @patch("reviewer.providers._httpx_mod")
    def test_structured_notes_render_in_markdown(self, mock_httpx):
        mock_httpx.post.return_value = _mock_httpx_response(
            json.dumps([
                {"title": "Unique security observation", "summary": "A novel concern about input validation", "confidence": "medium"},
            ])
        )
        provider = GitHubModelsProvider(token="test-token")
        ctx = _make_ctx(files={"app.py": "user_input = request.args.get('q')"})
        result = analyse(ctx, provider=provider)
        scan = _make_scan_result(result.findings)
        md = format_markdown(
            scan,
            concerns=result.concerns,
            observations=result.observations,
            provider_notes=result.provider_notes,
        )
        # If notes survived suppression, they should be in the markdown
        if result.provider_notes:
            assert "Additional Review Notes" in md

    def test_mock_provider_structured_notes_in_pipeline(self):
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        result = analyse(ctx, provider=MockProvider())
        assert isinstance(result.provider_notes, list)
        assert all(isinstance(n, CandidateNote) for n in result.provider_notes)

    def test_reasoning_result_has_provider_notes_field(self):
        from reviewer.planner import build_review_plan
        ctx = _make_ctx(files={"app.py": "code"})
        plan = build_review_plan(ctx)
        result = run_reasoning(ctx, plan=plan, provider=MockProvider())
        assert hasattr(result, "provider_notes")
        assert isinstance(result.provider_notes, list)
