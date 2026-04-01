"""Tests for provider evidence improvement (ADR-043).

Validates that:
- Provider requests now include actual changed code/snippet content
- Review targets are bounded and prioritized
- Relevant files are prioritized over irrelevant ones
- Code evidence is tied to the right paths
- Low-signal scenarios do not get huge irrelevant prompts
- Provider note trust boundaries remain unchanged
- ScanResult unchanged
- Scoring unchanged
- Realistic endpoint/authz-sensitive scenarios include code evidence
- Fixture/test-only noise does not drive vague provider output

No live provider credentials required.
"""

from __future__ import annotations

from reviewer.models import (
    PRContent,
    PRFile,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewBundle,
    ReviewBundleItem,
    ReviewConcern,
    ReviewMemory,
    ReviewMemoryEntry,
    ReviewObservation,
    ReviewPlan,
)
from reviewer.prompt_builder import (
    _MAX_EXCERPT_CHARS,
    _MAX_REVIEW_TARGETS,
    _REASON_PRIORITY,
    _bounded_excerpt,
    _build_review_targets,
    build_reasoning_request,
)
from reviewer.providers import (
    DisabledProvider,
    MockProvider,
    ReasoningRequest,
    _format_user_prompt,
)
from reviewer.engine import analyse
from reviewer.planner import build_review_plan
from reviewer.bundle import build_review_bundle
from schemas.findings import Category, Confidence, Finding, Severity


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


def _make_bundle(items: list[dict] | None = None) -> ReviewBundle:
    bundle_items = []
    if items:
        for item in items:
            bundle_items.append(ReviewBundleItem(**item))
    return ReviewBundle(items=bundle_items)


def _make_finding(
    category: str = "secrets",
    title: str = "Hardcoded secret",
    file: str = "config.py",
) -> Finding:
    return Finding(
        category=Category(category),
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        title=title,
        description="Test finding",
        file=file,
    )


# ======================================================================
# 1. Provider request includes actual changed code content
# ======================================================================


class TestCodeEvidenceInRequest:
    """Provider request now includes actual changed code/snippet content."""

    def test_review_targets_contain_code_excerpt(self):
        """Bundle items with content produce review targets with code_excerpt."""
        bundle = _make_bundle(items=[
            {
                "path": "src/auth/login.py",
                "content": "def login(user, password):\n    return verify(user, password)\n",
                "review_reason": "auth_area",
                "focus_areas": ["authentication"],
            },
        ])
        ctx = _make_ctx(files={"src/auth/login.py": "def login(user, password):\n    return verify(user, password)\n"})
        req = build_reasoning_request(ctx, bundle=bundle)

        assert req.has_review_targets
        assert len(req.review_targets) == 1
        target = req.review_targets[0]
        assert target["path"] == "src/auth/login.py"
        assert "def login(user, password)" in target["code_excerpt"]
        assert target["reason"] == "auth_area"
        assert "authentication" in target["focus_areas"]

    def test_review_targets_include_related_paths(self):
        """Related paths from bundle item are included in review target."""
        bundle = _make_bundle(items=[
            {
                "path": "src/auth/login.py",
                "content": "login code",
                "review_reason": "auth_area",
                "focus_areas": ["authentication"],
                "related_paths": ["src/auth/session.py", "src/auth/middleware.py"],
            },
        ])
        ctx = _make_ctx(files={"src/auth/login.py": "login code"})
        req = build_reasoning_request(ctx, bundle=bundle)

        target = req.review_targets[0]
        assert "related_paths" in target
        assert "src/auth/session.py" in target["related_paths"]

    def test_review_targets_include_memory_context(self):
        """Memory context from bundle item is included in review target."""
        bundle = _make_bundle(items=[
            {
                "path": "src/auth/login.py",
                "content": "login code",
                "review_reason": "auth_area",
                "focus_areas": [],
                "memory_context": ["authentication: prior JWT vulnerability"],
            },
        ])
        ctx = _make_ctx(files={"src/auth/login.py": "login code"})
        req = build_reasoning_request(ctx, bundle=bundle)

        target = req.review_targets[0]
        assert "memory_context" in target
        assert "prior JWT vulnerability" in target["memory_context"]

    def test_review_targets_include_baseline_context(self):
        """Baseline context from bundle item is included in review target."""
        bundle = _make_bundle(items=[
            {
                "path": "src/auth/login.py",
                "content": "login code",
                "review_reason": "auth_area",
                "focus_areas": [],
                "baseline_context": ["repo auth patterns: jwt, oauth"],
            },
        ])
        ctx = _make_ctx(files={"src/auth/login.py": "login code"})
        req = build_reasoning_request(ctx, bundle=bundle)

        target = req.review_targets[0]
        assert "baseline_context" in target
        assert "jwt" in target["baseline_context"]

    def test_code_evidence_appears_in_formatted_prompt(self):
        """When review targets are present, the user prompt contains code."""
        req = ReasoningRequest(
            changed_files_summary=[{"path": "auth.py", "review_reason": "auth_area", "focus_areas": ""}],
            review_targets=[{
                "path": "auth.py",
                "reason": "auth_area",
                "focus_areas": "authentication",
                "code_excerpt": "def verify_token(token):\n    return jwt.decode(token)\n",
            }],
        )
        prompt = _format_user_prompt(req)
        assert "REVIEW TARGETS" in prompt
        assert "def verify_token(token)" in prompt
        assert "```" in prompt  # Code block markers

    def test_no_review_targets_when_no_bundle(self):
        """Without a bundle, no review targets are produced."""
        ctx = _make_ctx(files={"app.py": "print('hello')"})
        req = build_reasoning_request(ctx)
        assert not req.has_review_targets
        assert req.review_targets == []

    def test_empty_bundle_produces_no_targets(self):
        """An empty bundle produces no review targets."""
        bundle = _make_bundle(items=[])
        ctx = _make_ctx(files={"app.py": "code"})
        req = build_reasoning_request(ctx, bundle=bundle)
        assert not req.has_review_targets

    def test_empty_content_produces_empty_excerpt(self):
        """Bundle items with empty content produce empty code_excerpt."""
        bundle = _make_bundle(items=[
            {
                "path": "empty.py",
                "content": "",
                "review_reason": "changed_file",
                "focus_areas": [],
            },
        ])
        ctx = _make_ctx(files={"empty.py": ""})
        req = build_reasoning_request(ctx, bundle=bundle)
        assert req.review_targets[0]["code_excerpt"] == ""


# ======================================================================
# 2. Review targets are bounded
# ======================================================================


class TestReviewTargetsBounding:
    """Request remains bounded and does not include the entire world."""

    def test_max_review_targets_bounded(self):
        """No more than _MAX_REVIEW_TARGETS items are included."""
        items = [
            {
                "path": f"file_{i}.py",
                "content": f"content_{i}",
                "review_reason": "changed_file",
                "focus_areas": [],
            }
            for i in range(20)
        ]
        bundle = _make_bundle(items=items)
        targets = _build_review_targets(bundle)
        assert len(targets) <= _MAX_REVIEW_TARGETS

    def test_code_excerpt_truncated_for_large_files(self):
        """Large file content is truncated to _MAX_EXCERPT_CHARS."""
        large_content = "x" * 5000
        excerpt = _bounded_excerpt(large_content)
        assert len(excerpt) <= _MAX_EXCERPT_CHARS + len("\n... [truncated]")
        assert excerpt.endswith("[truncated]")

    def test_small_content_not_truncated(self):
        """Content within the limit is not truncated."""
        small_content = "def hello():\n    return 'hi'\n"
        excerpt = _bounded_excerpt(small_content)
        assert excerpt == small_content
        assert "[truncated]" not in excerpt

    def test_no_review_targets_section_in_prompt_when_absent(self):
        """Formatted prompt does not include REVIEW TARGETS when empty."""
        req = ReasoningRequest(
            changed_files_summary=[{"path": "a.py", "review_reason": "changed_file", "focus_areas": ""}],
        )
        prompt = _format_user_prompt(req)
        assert "REVIEW TARGETS" not in prompt


# ======================================================================
# 3. Relevant files are prioritized over irrelevant ones
# ======================================================================


class TestReviewTargetPrioritization:
    """Review targets prioritize security-relevant files."""

    def test_sensitive_auth_first(self):
        """sensitive_auth items come before changed_file items."""
        bundle = _make_bundle(items=[
            {"path": "util.py", "content": "utils", "review_reason": "changed_file", "focus_areas": []},
            {"path": "auth/login.py", "content": "auth code", "review_reason": "sensitive_auth", "focus_areas": ["authentication"]},
            {"path": "readme.md", "content": "docs", "review_reason": "changed_file", "focus_areas": []},
        ])
        targets = _build_review_targets(bundle)
        assert targets[0]["path"] == "auth/login.py"
        assert targets[0]["reason"] == "sensitive_auth"

    def test_api_surface_before_changed_file(self):
        """api_surface items come before changed_file items."""
        bundle = _make_bundle(items=[
            {"path": "util.py", "content": "utils", "review_reason": "changed_file", "focus_areas": []},
            {"path": "routes/api.py", "content": "router code", "review_reason": "api_surface", "focus_areas": ["authentication"]},
        ])
        targets = _build_review_targets(bundle)
        assert targets[0]["path"] == "routes/api.py"

    def test_auth_area_before_plain_changed(self):
        """auth_area items come before changed_file items."""
        bundle = _make_bundle(items=[
            {"path": "test_helper.py", "content": "test", "review_reason": "changed_file", "focus_areas": []},
            {"path": "middleware/auth.py", "content": "auth middleware", "review_reason": "auth_area", "focus_areas": []},
        ])
        targets = _build_review_targets(bundle)
        assert targets[0]["path"] == "middleware/auth.py"

    def test_priority_order_comprehensive(self):
        """Full priority order: sensitive_auth > api_surface > auth_area > sensitive_path > changed_file."""
        bundle = _make_bundle(items=[
            {"path": "e.py", "content": "e", "review_reason": "changed_file", "focus_areas": []},
            {"path": "d.py", "content": "d", "review_reason": "sensitive_path", "focus_areas": []},
            {"path": "c.py", "content": "c", "review_reason": "auth_area", "focus_areas": []},
            {"path": "b.py", "content": "b", "review_reason": "api_surface", "focus_areas": []},
            {"path": "a.py", "content": "a", "review_reason": "sensitive_auth", "focus_areas": []},
        ])
        targets = _build_review_targets(bundle)
        reasons = [t["reason"] for t in targets]
        assert reasons == ["sensitive_auth", "api_surface", "auth_area", "sensitive_path", "changed_file"]

    def test_only_top_n_included_when_many_files(self):
        """When more than _MAX_REVIEW_TARGETS files exist, only top-N prioritized are included."""
        items = [
            {"path": "auth/critical.py", "content": "critical", "review_reason": "sensitive_auth", "focus_areas": []},
        ] + [
            {"path": f"other_{i}.py", "content": f"code_{i}", "review_reason": "changed_file", "focus_areas": []}
            for i in range(20)
        ]
        bundle = _make_bundle(items=items)
        targets = _build_review_targets(bundle)
        assert len(targets) <= _MAX_REVIEW_TARGETS
        assert targets[0]["path"] == "auth/critical.py"


# ======================================================================
# 4. Code evidence is tied to the right paths
# ======================================================================


class TestEvidencePathBinding:
    """Code evidence is correctly tied to file paths."""

    def test_each_target_code_matches_path(self):
        """Code excerpt corresponds to the bundle item's content for that path."""
        bundle = _make_bundle(items=[
            {"path": "auth.py", "content": "def authenticate():\n    pass\n", "review_reason": "auth_area", "focus_areas": []},
            {"path": "config.py", "content": "DEBUG = True\n", "review_reason": "sensitive_path", "focus_areas": []},
        ])
        targets = _build_review_targets(bundle)
        by_path = {t["path"]: t for t in targets}
        assert "def authenticate()" in by_path["auth.py"]["code_excerpt"]
        assert "DEBUG = True" in by_path["config.py"]["code_excerpt"]

    def test_formatted_prompt_ties_code_to_path(self):
        """In the formatted prompt, code excerpts appear under their path headings."""
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "auth_area", "focus_areas": ""},
            ],
            review_targets=[
                {
                    "path": "auth.py",
                    "reason": "auth_area",
                    "focus_areas": "authentication",
                    "code_excerpt": "def verify_jwt(token):\n    return decode(token)\n",
                },
            ],
        )
        prompt = _format_user_prompt(req)
        # Path heading appears before code
        path_idx = prompt.index("### auth.py")
        code_idx = prompt.index("def verify_jwt(token)")
        assert path_idx < code_idx


# ======================================================================
# 5. Low-signal scenarios do not get huge irrelevant prompts
# ======================================================================


class TestLowSignalBounding:
    """Low-signal scenarios stay bounded and quiet."""

    def test_low_signal_files_still_bounded(self):
        """Even if all files are changed_file, targets are bounded."""
        items = [
            {"path": f"util_{i}.py", "content": f"code_{i}", "review_reason": "changed_file", "focus_areas": []}
            for i in range(30)
        ]
        bundle = _make_bundle(items=items)
        targets = _build_review_targets(bundle)
        assert len(targets) <= _MAX_REVIEW_TARGETS

    def test_docs_only_pr_produces_targets_but_low_priority(self):
        """Documentation-only bundles produce targets but all are changed_file."""
        bundle = _make_bundle(items=[
            {"path": "README.md", "content": "# Readme\n", "review_reason": "changed_file", "focus_areas": []},
            {"path": "CHANGELOG.md", "content": "# Changes\n", "review_reason": "changed_file", "focus_areas": []},
        ])
        targets = _build_review_targets(bundle)
        assert all(t["reason"] == "changed_file" for t in targets)


# ======================================================================
# 6. Provider note trust boundaries remain unchanged
# ======================================================================


class TestTrustBoundariesPreserved:
    """Provider output with code evidence does not breach trust boundaries."""

    def test_disabled_provider_returns_empty_with_evidence(self):
        """DisabledProvider returns empty response even with review targets."""
        provider = DisabledProvider()
        req = ReasoningRequest(
            changed_files_summary=[{"path": "auth.py", "review_reason": "auth_area", "focus_areas": ""}],
            review_targets=[{
                "path": "auth.py",
                "reason": "auth_area",
                "focus_areas": "authentication",
                "code_excerpt": "def login(): pass",
            }],
        )
        resp = provider.reason(req)
        assert not resp.has_content
        assert resp.candidate_findings == []

    def test_mock_provider_returns_only_candidate_notes(self):
        """MockProvider with review targets still produces only candidate notes."""
        provider = MockProvider()
        req = ReasoningRequest(
            changed_files_summary=[{"path": "auth.py", "review_reason": "auth_area", "focus_areas": "authentication"}],
            review_targets=[{
                "path": "auth.py",
                "reason": "auth_area",
                "focus_areas": "authentication",
                "code_excerpt": "def login(): pass",
            }],
        )
        resp = provider.reason(req)
        assert resp.candidate_findings == []
        assert resp.provider_name == "mock"
        assert not resp.is_from_live_provider

    def test_provider_evidence_does_not_affect_scoring(self):
        """Full pipeline with code evidence does not change scoring behavior."""
        files = {
            "src/auth/login.py": "def login(user, pw):\n    return check(user, pw)\n",
        }
        ctx = _make_ctx(files=files, frameworks=["flask"], auth_patterns=["jwt"])
        result = analyse(ctx, provider=MockProvider())
        # No deterministic findings in this input → no findings
        assert result.findings == []


# ======================================================================
# 7. ScanResult unchanged
# ======================================================================


class TestScanResultUnchanged:
    """ScanResult schema is not modified by provider evidence changes."""

    def test_scan_result_schema_fields(self):
        """ScanResult still has only the canonical fields."""
        from schemas.findings import ScanResult
        fields = set(ScanResult.model_fields.keys())
        expected = {
            "scan_id", "repo", "pr_number", "commit_sha", "ref",
            "timestamp", "decision", "risk_score", "findings",
        }
        assert fields == expected

    def test_scan_result_no_provider_evidence_fields(self):
        """ScanResult does not contain review_targets or provider evidence."""
        from schemas.findings import ScanResult
        assert "review_targets" not in ScanResult.model_fields
        assert "code_excerpt" not in ScanResult.model_fields


# ======================================================================
# 8. Scoring unchanged
# ======================================================================


class TestScoringUnchanged:
    """Scoring derives from findings only, unaffected by code evidence."""

    def test_scoring_with_finding_unaffected(self):
        """A PR with a deterministic finding produces same findings regardless of provider."""
        files = {
            "config.py": 'DEBUG = True\nALLOWED_HOSTS = "*"\n',
        }
        ctx = _make_ctx(files=files)
        result_disabled = analyse(ctx, provider=DisabledProvider())
        result_mock = analyse(ctx, provider=MockProvider())

        # Same findings regardless of provider mode
        assert len(result_disabled.findings) == len(result_mock.findings)
        disabled_titles = sorted(f.title for f in result_disabled.findings)
        mock_titles = sorted(f.title for f in result_mock.findings)
        assert disabled_titles == mock_titles


# ======================================================================
# 9. Realistic endpoint/authz-sensitive scenario
# ======================================================================


class TestRealisticEndpointEvidence:
    """Realistic endpoint/authz-sensitive scenario includes code evidence."""

    def test_auth_route_code_in_provider_request(self):
        """A realistic auth route file appears in review targets with code."""
        auth_code = (
            "from flask import Flask, request, jsonify\n"
            "\n"
            "app = Flask(__name__)\n"
            "\n"
            "@app.route('/api/users', methods=['GET'])\n"
            "def list_users():\n"
            "    # No authentication check!\n"
            "    users = db.query('SELECT * FROM users')\n"
            "    return jsonify(users)\n"
            "\n"
            "@app.route('/api/admin/delete', methods=['POST'])\n"
            "def admin_delete():\n"
            "    user_id = request.json['user_id']\n"
            "    db.execute(f'DELETE FROM users WHERE id = {user_id}')\n"
            "    return jsonify({'status': 'deleted'})\n"
        )
        files = {"src/routes/users.py": auth_code}
        ctx = _make_ctx(files=files, frameworks=["flask"], auth_patterns=["jwt"])
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        req = build_reasoning_request(ctx, plan=plan, bundle=bundle)

        # Review targets should include the auth route code
        assert req.has_review_targets
        target_paths = [t["path"] for t in req.review_targets]
        assert "src/routes/users.py" in target_paths

        # The target should contain the actual route code
        route_target = next(t for t in req.review_targets if t["path"] == "src/routes/users.py")
        assert "@app.route" in route_target["code_excerpt"]
        assert "list_users" in route_target["code_excerpt"]
        assert "admin_delete" in route_target["code_excerpt"]

    def test_controller_with_auth_code_evidence(self):
        """A controller with auth logic includes code evidence in request."""
        controller_code = (
            "class UserController:\n"
            "    def create(self, request):\n"
            "        if not request.user.is_authenticated:\n"
            "            raise PermissionDenied\n"
            "        user = User.objects.create(**request.data)\n"
            "        return Response(user.serialize())\n"
        )
        files = {"src/controllers/user_controller.py": controller_code}
        ctx = _make_ctx(files=files)
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        req = build_reasoning_request(ctx, plan=plan, bundle=bundle)

        # Should have code evidence
        assert req.has_review_targets
        target = req.review_targets[0]
        assert "UserController" in target["code_excerpt"]
        assert "is_authenticated" in target["code_excerpt"]

    def test_formatted_prompt_includes_route_code(self):
        """The formatted user prompt includes route code, not just path names."""
        auth_code = (
            "@app.route('/api/users', methods=['GET'])\n"
            "def list_users():\n"
            "    return jsonify(db.query_all())\n"
        )
        files = {"src/routes/users.py": auth_code}
        ctx = _make_ctx(files=files, frameworks=["flask"])
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        req = build_reasoning_request(ctx, plan=plan, bundle=bundle)
        prompt = _format_user_prompt(req)

        assert "@app.route" in prompt
        assert "list_users" in prompt
        assert "REVIEW TARGETS" in prompt


# ======================================================================
# 10. Fixture/test-only noise reduction
# ======================================================================


class TestTestOnlyNoiseReduction:
    """Test-only files are low-priority and don't dominate review targets."""

    def test_auth_file_prioritized_over_test_files(self):
        """Auth files appear before test files in review targets."""
        bundle = _make_bundle(items=[
            {"path": "tests/test_login.py", "content": "def test_login(): pass", "review_reason": "changed_file", "focus_areas": []},
            {"path": "tests/test_signup.py", "content": "def test_signup(): pass", "review_reason": "changed_file", "focus_areas": []},
            {"path": "src/auth/login.py", "content": "def login(): verify()", "review_reason": "sensitive_auth", "focus_areas": ["authentication"]},
            {"path": "tests/test_utils.py", "content": "def test_util(): pass", "review_reason": "changed_file", "focus_areas": []},
        ])
        targets = _build_review_targets(bundle)
        assert targets[0]["path"] == "src/auth/login.py"
        assert targets[0]["reason"] == "sensitive_auth"


# ======================================================================
# Prompt rendering regression tests
# ======================================================================


class TestPromptRendering:
    """Verify the formatted prompt renders review targets correctly."""

    def test_review_targets_section_structure(self):
        """Review targets section has correct structure with headers and code blocks."""
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "auth.py", "review_reason": "auth_area", "focus_areas": "authentication"},
            ],
            review_targets=[
                {
                    "path": "auth.py",
                    "reason": "auth_area",
                    "focus_areas": "authentication",
                    "code_excerpt": "def check_token(t):\n    return decode(t)\n",
                    "related_paths": "session.py, middleware.py",
                    "memory_context": "authentication: prior issue with token validation",
                    "baseline_context": "repo auth patterns: jwt, oauth",
                },
            ],
        )
        prompt = _format_user_prompt(req)

        assert "### auth.py" in prompt
        assert "Review reason: auth_area" in prompt
        assert "Focus areas: authentication" in prompt
        assert "Related changed files: session.py, middleware.py" in prompt
        assert "Prior review context: authentication: prior issue with token validation" in prompt
        assert "Baseline context: repo auth patterns: jwt, oauth" in prompt
        assert "def check_token(t)" in prompt

    def test_multiple_review_targets_rendered(self):
        """Multiple review targets each get their own section."""
        req = ReasoningRequest(
            changed_files_summary=[
                {"path": "a.py", "review_reason": "auth_area", "focus_areas": ""},
                {"path": "b.py", "review_reason": "sensitive_path", "focus_areas": ""},
            ],
            review_targets=[
                {"path": "a.py", "reason": "auth_area", "focus_areas": "", "code_excerpt": "code_a"},
                {"path": "b.py", "reason": "sensitive_path", "focus_areas": "", "code_excerpt": "code_b"},
            ],
        )
        prompt = _format_user_prompt(req)
        assert "### a.py" in prompt
        assert "### b.py" in prompt
        assert "code_a" in prompt
        assert "code_b" in prompt

    def test_evidence_instruction_in_prompt(self):
        """Prompt instructs provider to comment only when evidence supports observation."""
        req = ReasoningRequest(
            review_targets=[
                {"path": "x.py", "reason": "auth_area", "focus_areas": "", "code_excerpt": "code"},
            ],
        )
        prompt = _format_user_prompt(req)
        assert "comment only when" in prompt.lower() or "code evidence supports" in prompt.lower()


# ======================================================================
# System prompt evidence-awareness tests
# ======================================================================


class TestSystemPromptEvidence:
    """System prompt instructs provider to use code evidence."""

    def test_system_prompt_references_code_evidence(self):
        """System prompt mentions using code evidence from REVIEW TARGETS."""
        from reviewer.providers import _SYSTEM_PROMPT
        assert "REVIEW TARGETS" in _SYSTEM_PROMPT
        assert "code evidence" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_discourages_vague_path_based_observations(self):
        """System prompt discourages vague observations based only on file names."""
        from reviewer.providers import _SYSTEM_PROMPT
        assert "file names" in _SYSTEM_PROMPT.lower() or "file name" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_still_requires_uncertainty(self):
        """System prompt still requires hedged language."""
        from reviewer.providers import _SYSTEM_PROMPT
        assert "may" in _SYSTEM_PROMPT
        assert "could" in _SYSTEM_PROMPT


# ======================================================================
# Integration with full pipeline
# ======================================================================


class TestFullPipelineEvidence:
    """End-to-end: verify evidence flows through the full pipeline."""

    def test_pipeline_builds_review_targets_for_auth_pr(self):
        """Full pipeline builds review targets for an auth-sensitive PR."""
        files = {
            "src/auth/middleware.py": (
                "def require_auth(handler):\n"
                "    def wrapper(request):\n"
                "        if not request.headers.get('Authorization'):\n"
                "            return Response(status=401)\n"
                "        return handler(request)\n"
                "    return wrapper\n"
            ),
        }
        ctx = _make_ctx(files=files, auth_patterns=["jwt"])
        plan = build_review_plan(ctx)
        bundle = build_review_bundle(ctx, plan)
        req = build_reasoning_request(ctx, plan=plan, bundle=bundle)

        assert req.has_review_targets
        target = req.review_targets[0]
        assert "require_auth" in target["code_excerpt"]
        assert "Authorization" in target["code_excerpt"]

    def test_pipeline_evidence_does_not_leak_to_scan_result(self):
        """Review targets do not appear in the ScanResult schema."""
        from schemas.findings import ScanResult
        fields = set(ScanResult.model_fields.keys())
        assert "review_targets" not in fields
        assert "code_excerpt" not in fields
        # Also verify via full pipeline
        files = {"src/auth/login.py": "def login(): pass"}
        ctx = _make_ctx(files=files)
        result = analyse(ctx, provider=MockProvider())
        # AnalysisResult.findings are Finding objects — no review_targets field
        for f in result.findings:
            assert not hasattr(f, "review_targets")
            assert not hasattr(f, "code_excerpt")
