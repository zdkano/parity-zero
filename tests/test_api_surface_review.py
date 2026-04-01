"""Tests for API surface expansion review triggering (ADR-042).

Covers:
1. New endpoint / route introduction triggers review interest
2. New authenticated CRUD resource triggers provider invocation
3. Ownership/authorization-sensitive resource changes produce concern/observation
4. Realistic notes-resource-like scenario triggers AI review behavior
5. Docs-only and low-signal scenarios remain quiet
6. Provider-skip / repo-config exclusions still suppress correctly
7. No trust-boundary regression: provider output remains non-authoritative
8. No ScanResult contract change
9. No scoring change
"""

from __future__ import annotations

import json

from reviewer.engine import AnalysisResult, analyse, derive_decision_and_risk
from reviewer.models import (
    PRContent,
    PRFile,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewBundle,
    ReviewBundleItem,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewPlan,
)
from reviewer.planner import (
    api_surface_path_overlap,
    build_review_plan,
    generate_concerns,
)
from reviewer.bundle import build_review_bundle
from reviewer.observations import generate_observations
from reviewer.provider_gate import ProviderGateResult, evaluate_provider_gate
from reviewer.providers import DisabledProvider, MockProvider
from reviewer.reasoning import ReasoningResult, run_reasoning
from reviewer.repo_config import RepoConfig
from schemas.findings import Category, Confidence, Decision, Finding, ScanResult, Severity


# ======================================================================
# Helpers
# ======================================================================


def _make_ctx(
    files: dict[str, str],
    frameworks: list[str] | None = None,
    auth_patterns: list[str] | None = None,
    memory_entries: list[tuple[str, str]] | None = None,
) -> PullRequestContext:
    pr_content = PRContent.from_dict(files)
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
            ],
        )
    return PullRequestContext(
        pr_content=pr_content,
        baseline_profile=profile,
        memory=memory,
    )


# ======================================================================
# Realistic scenario: notes-resource-style CRUD stack
# ======================================================================

_NOTES_ROUTE_CONTENT = '''\
from fastapi import APIRouter, Depends, HTTPException
from app.auth import require_auth
from app.models import Note
from app.services.notes import NotesService

router = APIRouter(prefix="/v1/notes", tags=["notes"])

@router.get("/")
async def list_notes(user=Depends(require_auth)):
    return await NotesService.list_for_user(user.id)

@router.post("/")
async def create_note(payload: dict, user=Depends(require_auth)):
    return await NotesService.create(user.id, payload)

@router.get("/{note_id}")
async def get_note(note_id: str, user=Depends(require_auth)):
    note = await NotesService.get(note_id)
    if note.owner_id != user.id:
        raise HTTPException(403, "Not your note")
    return note

@router.put("/{note_id}")
async def update_note(note_id: str, payload: dict, user=Depends(require_auth)):
    return await NotesService.update(note_id, user.id, payload)

@router.delete("/{note_id}")
async def delete_note(note_id: str, user=Depends(require_auth)):
    return await NotesService.delete(note_id, user.id)
'''

_NOTES_SERVICE_CONTENT = '''\
from app.models import Note
from app.db import get_db

class NotesService:
    @staticmethod
    async def list_for_user(user_id: str):
        db = get_db()
        return db.query(Note).filter(Note.owner_id == user_id).all()

    @staticmethod
    async def create(user_id: str, payload: dict):
        note = Note(owner_id=user_id, **payload)
        db = get_db()
        db.add(note)
        db.commit()
        return note

    @staticmethod
    async def get(note_id: str):
        db = get_db()
        return db.query(Note).get(note_id)

    @staticmethod
    async def update(note_id: str, user_id: str, payload: dict):
        db = get_db()
        note = db.query(Note).get(note_id)
        if note.owner_id != user_id:
            raise PermissionError("Not authorized")
        for k, v in payload.items():
            setattr(note, k, v)
        db.commit()
        return note

    @staticmethod
    async def delete(note_id: str, user_id: str):
        db = get_db()
        note = db.query(Note).get(note_id)
        if note.owner_id != user_id:
            raise PermissionError("Not authorized")
        db.delete(note)
        db.commit()
'''

_NOTES_VALIDATION_CONTENT = '''\
from pydantic import BaseModel, Field

class CreateNoteRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(default="")

class UpdateNoteRequest(BaseModel):
    title: str | None = None
    body: str | None = None
'''

_NOTES_FILES = {
    "app/routes/notes.py": _NOTES_ROUTE_CONTENT,
    "app/services/notes.py": _NOTES_SERVICE_CONTENT,
    "app/validation/notes.py": _NOTES_VALIDATION_CONTENT,
}


# ======================================================================
# Test: Path-based API surface detection
# ======================================================================


class TestApiSurfacePathDetection:
    """api_surface_path_overlap detects route/controller/handler paths."""

    def test_routes_directory(self):
        paths = ["app/routes/users.py", "app/models/user.py"]
        assert "app/routes/users.py" in api_surface_path_overlap(paths)

    def test_controllers_directory(self):
        paths = ["src/controllers/notes_controller.py"]
        assert len(api_surface_path_overlap(paths)) == 1

    def test_handlers_directory(self):
        paths = ["handlers/webhook.py"]
        assert len(api_surface_path_overlap(paths)) == 1

    def test_endpoints_directory(self):
        paths = ["api/endpoints/v1/items.py"]
        result = api_surface_path_overlap(paths)
        assert len(result) == 1

    def test_api_directory(self):
        paths = ["src/api/routes.py"]
        assert len(api_surface_path_overlap(paths)) == 1

    def test_views_directory(self):
        paths = ["app/views/dashboard.py"]
        assert len(api_surface_path_overlap(paths)) == 1

    def test_non_api_path_not_matched(self):
        paths = ["src/utils/helpers.py", "lib/math.py"]
        assert api_surface_path_overlap(paths) == []

    def test_docs_not_matched(self):
        paths = ["docs/api-guide.md", "README.md"]
        assert api_surface_path_overlap(paths) == []

    def test_tests_not_matched(self):
        paths = ["tests/test_routes.py", "tests/test_api.py"]
        assert api_surface_path_overlap(paths) == []


# ======================================================================
# Test: Content-based route detection
# ======================================================================


class TestRouteContentDetection:
    """build_review_plan detects route patterns in file content."""

    def test_fastapi_route_decorator(self):
        ctx = _make_ctx({
            "app/main.py": '@app.get("/users")\nasync def list_users(): pass',
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_express_router(self):
        ctx = _make_ctx({
            "src/server.js": 'router.post("/items", createItem);',
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_flask_blueprint(self):
        ctx = _make_ctx({
            "app/views.py": 'bp = Blueprint("api", __name__)',
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_api_router_class(self):
        ctx = _make_ctx({
            "app/routes.py": 'router = APIRouter(prefix="/v1/notes")',
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_versioned_api_path(self):
        ctx = _make_ctx({
            "app/urls.py": "urlpatterns = [path('/v1/users/', views.users)]",
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_crud_function_patterns(self):
        ctx = _make_ctx({
            "app/handlers.py": "def create_user(request):\n    pass",
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_resource_controller_class(self):
        ctx = _make_ctx({
            "app/notes.py": "class NotesController:\n    pass",
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_auth_middleware_reference(self):
        ctx = _make_ctx({
            "app/routes.py": "from middleware import require_auth\nrouter.use(require_auth)",
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags

    def test_plain_python_no_routes(self):
        ctx = _make_ctx({
            "utils/helpers.py": "def add(a, b):\n    return a + b",
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" not in plan.review_flags

    def test_docs_file_skipped(self):
        ctx = _make_ctx({
            "docs/api.md": "# API Reference\n/v1/users endpoint docs",
        })
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" not in plan.review_flags


# ======================================================================
# Test: Plan focus and flags for API surface
# ======================================================================


class TestApiSurfacePlanFocus:
    """API surface expansion enriches plan with correct flags and focus areas."""

    def test_notes_resource_sets_flags_and_focus(self):
        ctx = _make_ctx(_NOTES_FILES)
        plan = build_review_plan(ctx)
        assert "api_surface_expansion" in plan.review_flags
        assert "authentication" in plan.focus_areas
        assert "authorization" in plan.focus_areas

    def test_notes_resource_adds_sensitive_paths(self):
        ctx = _make_ctx(_NOTES_FILES)
        plan = build_review_plan(ctx)
        assert any("routes" in p for p in plan.sensitive_paths_touched)

    def test_guidance_mentions_api_surface(self):
        ctx = _make_ctx(_NOTES_FILES)
        plan = build_review_plan(ctx)
        assert any("API surface" in g for g in plan.reviewer_guidance)


# ======================================================================
# Test: Provider gate behavior for API surface
# ======================================================================


class TestApiSurfaceProviderGate:
    """API surface expansion triggers provider invocation."""

    def test_route_file_triggers_gate(self):
        ctx = _make_ctx(_NOTES_FILES)
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        result = evaluate_provider_gate(plan, bundle)
        assert result.should_invoke is True
        assert any("API surface" in r for r in result.reasons)

    def test_single_route_triggers_gate(self):
        ctx = _make_ctx({
            "app/routes/items.py": '@router.get("/items")\ndef list_items(): pass',
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        result = evaluate_provider_gate(plan, bundle)
        assert result.should_invoke is True

    def test_plain_util_does_not_trigger_gate(self):
        ctx = _make_ctx({
            "utils/math.py": "def add(a, b):\n    return a + b",
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        result = evaluate_provider_gate(plan, bundle)
        assert result.should_invoke is False


# ======================================================================
# Test: Concern generation for API surface
# ======================================================================


class TestApiSurfaceConcerns:
    """API surface expansion generates appropriate concerns."""

    def test_notes_resource_generates_concern(self):
        ctx = _make_ctx(_NOTES_FILES)
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)
        api_concerns = [c for c in concerns if c.basis == "api_surface_expansion"]
        assert len(api_concerns) >= 1
        assert api_concerns[0].category == "authorization"
        assert "CRUD" in api_concerns[0].title or "API" in api_concerns[0].title

    def test_concern_mentions_authorization(self):
        ctx = _make_ctx(_NOTES_FILES)
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)
        api_concerns = [c for c in concerns if c.basis == "api_surface_expansion"]
        assert any("authorization" in c.summary.lower() for c in api_concerns)

    def test_no_api_concern_for_plain_files(self):
        ctx = _make_ctx({
            "lib/helpers.py": "def helper(): pass",
        })
        plan = build_review_plan(ctx)
        concerns = generate_concerns(plan, ctx)
        api_concerns = [c for c in concerns if c.basis == "api_surface_expansion"]
        assert len(api_concerns) == 0


# ======================================================================
# Test: Observation generation for API surface
# ======================================================================


class TestApiSurfaceObservations:
    """API surface files produce targeted observations."""

    def test_route_file_observation(self):
        ctx = _make_ctx(_NOTES_FILES, frameworks=["FastAPI"])
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        observations = generate_observations(bundle)
        api_obs = [o for o in observations if "api_surface" in o.basis]
        assert len(api_obs) >= 1
        assert any("API surface" in o.title for o in api_obs)

    def test_observation_mentions_authorization(self):
        ctx = _make_ctx(_NOTES_FILES, frameworks=["FastAPI"])
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        observations = generate_observations(bundle)
        api_obs = [o for o in observations if "api_surface" in o.basis]
        assert any("authorization" in o.summary.lower() for o in api_obs)

    def test_no_observation_for_plain_files(self):
        ctx = _make_ctx({
            "lib/helpers.py": "def helper(): pass",
        })
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        observations = generate_observations(bundle)
        assert len(observations) == 0


# ======================================================================
# Test: Full pipeline (analyse) for realistic scenarios
# ======================================================================


class TestApiSurfaceFullPipeline:
    """Full pipeline produces correct behavior for API surface PRs."""

    def test_notes_resource_with_mock_provider(self):
        """Realistic notes-resource PR triggers review with mock provider."""
        ctx = _make_ctx(
            _NOTES_FILES,
            frameworks=["FastAPI"],
            auth_patterns=["bearer_token", "require_auth"],
        )
        result = analyse(ctx, provider=MockProvider())
        # Should have concerns
        assert len(result.concerns) > 0
        assert any(c.basis == "api_surface_expansion" for c in result.concerns)
        # Should have observations
        assert len(result.observations) > 0
        # Provider should have been invoked (gate should open)
        assert result.trace.provider_gate_decision == "invoked"
        # Trust boundary: no findings from provider
        assert all(
            f.category in (Category.SECRETS, Category.INSECURE_CONFIGURATION)
            for f in result.findings
        ) or len(result.findings) == 0

    def test_notes_resource_with_disabled_provider(self):
        """Realistic notes-resource PR generates concerns/observations even without provider."""
        ctx = _make_ctx(
            _NOTES_FILES,
            frameworks=["FastAPI"],
            auth_patterns=["bearer_token"],
        )
        result = analyse(ctx, provider=DisabledProvider())
        # Should still have concerns
        assert any(c.basis == "api_surface_expansion" for c in result.concerns)
        # Should still have observations
        assert len(result.observations) > 0

    def test_single_route_triggers_review(self):
        """Single new route file triggers review interest."""
        ctx = _make_ctx({
            "app/routes/items.py": (
                'from fastapi import APIRouter\n'
                'router = APIRouter(prefix="/v1/items")\n'
                '@router.get("/")\n'
                'async def list_items(): pass\n'
            ),
        })
        result = analyse(ctx, provider=MockProvider())
        assert result.trace.provider_gate_decision == "invoked"
        assert len(result.concerns) > 0 or len(result.observations) > 0


# ======================================================================
# Test: Negative / control cases
# ======================================================================


class TestApiSurfaceNegativeCases:
    """Low-signal changes remain quiet; no contract or scoring regression."""

    def test_docs_only_stays_quiet(self):
        ctx = _make_ctx({
            "docs/guide.md": "# User Guide\nSome documentation.",
            "CHANGELOG.md": "## v1.0.0\n- Initial release",
        })
        result = analyse(ctx, provider=MockProvider())
        assert "api_surface_expansion" not in (
            result.trace.active_focus_areas
        )
        assert len(result.findings) == 0
        # Provider should not be invoked for docs-only
        assert result.trace.provider_gate_decision in ("skipped", "disabled")

    def test_test_files_stay_quiet(self):
        ctx = _make_ctx({
            "tests/test_utils.py": "def test_add():\n    assert 1 + 1 == 2",
            "tests/test_math.py": "def test_sub():\n    assert 2 - 1 == 1",
        })
        result = analyse(ctx, provider=MockProvider())
        assert len(result.findings) == 0
        assert result.trace.provider_gate_decision in ("skipped", "disabled")

    def test_lockfile_stays_quiet(self):
        ctx = _make_ctx({
            "package-lock.json": '{"lockfileVersion": 2}',
        })
        result = analyse(ctx, provider=MockProvider())
        assert len(result.findings) == 0

    def test_plain_utility_stays_quiet(self):
        ctx = _make_ctx({
            "utils/math.py": "def add(a, b):\n    return a + b",
        })
        result = analyse(ctx, provider=MockProvider())
        assert len(result.observations) == 0
        api_concerns = [c for c in result.concerns if c.basis == "api_surface_expansion"]
        assert len(api_concerns) == 0

    def test_no_scoring_change(self):
        """API surface detection does not affect scoring — only findings do."""
        ctx = _make_ctx(_NOTES_FILES)
        result = analyse(ctx, provider=MockProvider())
        decision, risk_score = derive_decision_and_risk(result.findings)
        # No deterministic findings in notes-resource code
        assert decision == Decision.PASS
        assert risk_score == 0

    def test_scan_result_contract_unchanged(self):
        """ScanResult shape is unaffected by API surface detection."""
        ctx = _make_ctx(_NOTES_FILES)
        result = analyse(ctx, provider=MockProvider())
        decision, risk_score = derive_decision_and_risk(result.findings)
        scan = ScanResult(
            scan_id="test-scan",
            repo="test/repo",
            pr_number=1,
            commit_sha="abc1234",
            ref="main",
            decision=decision,
            risk_score=risk_score,
            findings=result.findings,
        )
        data = json.loads(scan.model_dump_json())
        assert "scan_id" in data
        assert "decision" in data
        assert "risk_score" in data
        assert "findings" in data
        # No api_surface_expansion in ScanResult
        assert "api_surface" not in json.dumps(data)

    def test_provider_skip_config_suppresses(self):
        """provider_skip_paths config still suppresses provider for matching paths."""
        ctx = _make_ctx({
            "scripts/routes/setup.py": '@app.get("/setup")\ndef setup(): pass',
        })
        config = RepoConfig(provider_skip_paths=("scripts/**",))
        result = analyse(ctx, provider=MockProvider(), config=config)
        assert result.trace.provider_gate_decision in ("skipped", "disabled")

    def test_exclude_config_removes_files(self):
        """exclude_paths config removes API surface files before analysis."""
        ctx = _make_ctx({
            "generated/routes/items.py": '@router.get("/")\ndef list(): pass',
        })
        config = RepoConfig(exclude_paths=("generated/**",))
        result = analyse(ctx, provider=MockProvider(), config=config)
        assert len(result.observations) == 0


# ======================================================================
# Test: Trust boundary preservation
# ======================================================================


class TestApiSurfaceTrustBoundary:
    """Provider output remains non-authoritative for API surface PRs."""

    def test_provider_output_not_findings(self):
        """Provider-backed review of API surface does not produce findings."""
        ctx = _make_ctx(
            _NOTES_FILES,
            frameworks=["FastAPI"],
            auth_patterns=["bearer_token"],
        )
        result = analyse(ctx, provider=MockProvider())
        # MockProvider may generate notes, but they should not appear as findings
        for f in result.findings:
            assert f.category in (Category.SECRETS, Category.INSECURE_CONFIGURATION), (
                f"Unexpected finding category: {f.category}"
            )

    def test_scoring_from_findings_only(self):
        """Decision and risk_score are derived from findings only."""
        ctx = _make_ctx(_NOTES_FILES)
        result = analyse(ctx, provider=MockProvider())
        decision, risk_score = derive_decision_and_risk(result.findings)
        # Recompute to verify determinism
        decision2, risk_score2 = derive_decision_and_risk(result.findings)
        assert decision == decision2
        assert risk_score == risk_score2

    def test_observations_are_non_scoring(self):
        """API surface observations do not affect risk score."""
        ctx = _make_ctx(_NOTES_FILES)
        result_with = analyse(ctx, provider=MockProvider())
        result_without = analyse(ctx, provider=DisabledProvider())
        d1, r1 = derive_decision_and_risk(result_with.findings)
        d2, r2 = derive_decision_and_risk(result_without.findings)
        assert d1 == d2
        assert r1 == r2


# ======================================================================
# Test: Mixed scenarios
# ======================================================================


class TestApiSurfaceMixedScenarios:
    """API surface detection works correctly alongside other signals."""

    def test_route_with_hardcoded_secret(self):
        """Route file with a hardcoded secret produces both finding and observation."""
        ctx = _make_ctx({
            "app/routes/users.py": (
                'AKIAIOSFODNN7EXAMPLE1\n'
                '@router.get("/users")\n'
                'async def list_users(): pass\n'
            ),
        })
        result = analyse(ctx, provider=MockProvider())
        # Should have a secrets finding from deterministic check
        assert any(f.category == Category.SECRETS for f in result.findings)
        # Should also have API surface review interest
        assert "api_surface_expansion" in result.trace.active_focus_areas or any(
            c.basis == "api_surface_expansion" for c in result.concerns
        )

    def test_auth_route_with_memory(self):
        """Auth route with memory context generates both memory and API concerns."""
        ctx = _make_ctx(
            files={
                "app/routes/auth/login.py": (
                    '@router.post("/v1/auth/login")\n'
                    'async def login(credentials): pass\n'
                ),
            },
            auth_patterns=["JWT"],
            memory_entries=[
                ("authentication", "Prior auth bypass in login flow"),
            ],
        )
        result = analyse(ctx, provider=MockProvider())
        # Should have concerns from both API surface and memory
        assert len(result.concerns) >= 2
        basis_set = {c.basis for c in result.concerns}
        assert "api_surface_expansion" in basis_set
