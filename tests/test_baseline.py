"""Tests for baseline repository profiler and context models.

Covers:
- RepoSecurityProfile model construction and fields
- BaselineScanResult model construction
- ReviewMemoryEntry and ReviewMemory models
- PullRequestContext model and backward compatibility
- Baseline profiler basic behaviour
  - language detection from file extensions
  - framework hints from filenames and content
  - sensitive path detection
  - auth signal detection
  - empty/minimal input handling
"""

from reviewer.baseline import profile_repository
from reviewer.models import (
    BaselineScanResult,
    PRContent,
    PRFile,
    PullRequestContext,
    RepoSecurityProfile,
    ReviewMemory,
    ReviewMemoryEntry,
)


# ======================================================================
# RepoSecurityProfile model tests
# ======================================================================


class TestRepoSecurityProfile:
    """Tests for RepoSecurityProfile dataclass."""

    def test_default_construction(self):
        profile = RepoSecurityProfile()
        assert profile.repo == ""
        assert profile.languages == []
        assert profile.frameworks == []
        assert profile.sensitive_paths == []
        assert profile.auth_patterns == []
        assert profile.notes == []
        assert profile.profiled_at  # non-empty timestamp

    def test_construction_with_values(self):
        profile = RepoSecurityProfile(
            repo="acme/webapp",
            languages=["python", "javascript"],
            frameworks=["fastapi"],
            sensitive_paths=["src/auth/login.py"],
            auth_patterns=["JWT usage detected"],
            notes=["Test note"],
        )
        assert profile.repo == "acme/webapp"
        assert "python" in profile.languages
        assert "fastapi" in profile.frameworks
        assert len(profile.sensitive_paths) == 1
        assert len(profile.auth_patterns) == 1

    def test_profiled_at_is_auto_generated(self):
        p1 = RepoSecurityProfile()
        p2 = RepoSecurityProfile()
        assert p1.profiled_at
        assert p2.profiled_at


# ======================================================================
# BaselineScanResult model tests
# ======================================================================


class TestBaselineScanResult:
    """Tests for BaselineScanResult dataclass."""

    def test_default_construction(self):
        result = BaselineScanResult()
        assert isinstance(result.profile, RepoSecurityProfile)
        assert result.files_analysed == 0
        assert result.notes == []

    def test_construction_with_profile(self):
        profile = RepoSecurityProfile(repo="test/repo", languages=["go"])
        result = BaselineScanResult(profile=profile, files_analysed=10)
        assert result.profile.repo == "test/repo"
        assert result.files_analysed == 10


# ======================================================================
# ReviewMemoryEntry and ReviewMemory model tests
# ======================================================================


class TestReviewMemoryEntry:
    """Tests for ReviewMemoryEntry dataclass."""

    def test_default_construction(self):
        entry = ReviewMemoryEntry()
        assert entry.category == ""
        assert entry.summary == ""
        assert entry.repo == ""
        assert entry.recorded_at  # non-empty timestamp

    def test_construction_with_values(self):
        entry = ReviewMemoryEntry(
            category="secrets",
            summary="Recurring AWS key exposure in deploy scripts",
            repo="acme/webapp",
        )
        assert entry.category == "secrets"
        assert "AWS" in entry.summary


class TestReviewMemory:
    """Tests for ReviewMemory dataclass."""

    def test_default_construction(self):
        memory = ReviewMemory()
        assert memory.repo == ""
        assert memory.entries == []
        assert memory.entry_count == 0

    def test_entry_count(self):
        memory = ReviewMemory(
            entries=[
                ReviewMemoryEntry(category="secrets"),
                ReviewMemoryEntry(category="auth"),
            ]
        )
        assert memory.entry_count == 2

    def test_categories(self):
        memory = ReviewMemory(
            entries=[
                ReviewMemoryEntry(category="secrets"),
                ReviewMemoryEntry(category="auth"),
                ReviewMemoryEntry(category="secrets"),
            ]
        )
        cats = memory.categories()
        assert "secrets" in cats
        assert "auth" in cats
        assert len(cats) == 2  # deduplicated

    def test_categories_empty(self):
        memory = ReviewMemory()
        assert memory.categories() == []


# ======================================================================
# PullRequestContext model tests
# ======================================================================


class TestPullRequestContext:
    """Tests for PullRequestContext dataclass."""

    def test_default_construction(self):
        ctx = PullRequestContext()
        assert ctx.file_count == 0
        assert ctx.has_baseline is False
        assert ctx.has_memory is False

    def test_from_pr_content(self):
        pr = PRContent.from_dict({"a.py": "x = 1"})
        ctx = PullRequestContext.from_pr_content(pr)
        assert ctx.file_count == 1
        assert ctx.has_baseline is False

    def test_from_dict(self):
        ctx = PullRequestContext.from_dict({"b.py": "y = 2"})
        assert ctx.file_count == 1
        assert ctx.pr_content.paths == ["b.py"]

    def test_with_baseline(self):
        profile = RepoSecurityProfile(repo="acme/webapp")
        ctx = PullRequestContext(
            pr_content=PRContent.from_dict({"c.py": "z = 3"}),
            baseline_profile=profile,
        )
        assert ctx.has_baseline is True
        assert ctx.baseline_profile.repo == "acme/webapp"

    def test_with_memory(self):
        memory = ReviewMemory(
            entries=[ReviewMemoryEntry(category="secrets")]
        )
        ctx = PullRequestContext(
            pr_content=PRContent.from_dict({"d.py": "w = 4"}),
            memory=memory,
        )
        assert ctx.has_memory is True
        assert ctx.memory.entry_count == 1

    def test_with_baseline_and_memory(self):
        profile = RepoSecurityProfile(repo="acme/webapp")
        memory = ReviewMemory(entries=[ReviewMemoryEntry(category="auth")])
        ctx = PullRequestContext(
            pr_content=PRContent.from_dict({"e.py": "v = 5"}),
            baseline_profile=profile,
            memory=memory,
        )
        assert ctx.has_baseline is True
        assert ctx.has_memory is True
        assert ctx.file_count == 1


# ======================================================================
# Baseline profiler tests
# ======================================================================


class TestBaselineProfiler:
    """Tests for the baseline repository profiler."""

    def test_empty_input(self):
        result = profile_repository({})
        assert isinstance(result, BaselineScanResult)
        assert result.files_analysed == 0
        assert result.profile.languages == []
        assert result.profile.frameworks == []
        assert any("No files" in n for n in result.notes)

    def test_produces_repo_security_profile(self):
        result = profile_repository({"app.py": "x = 1"}, repo="acme/webapp")
        assert isinstance(result.profile, RepoSecurityProfile)
        assert result.profile.repo == "acme/webapp"
        assert result.files_analysed == 1

    def test_detects_python(self):
        result = profile_repository({"app.py": "print('hello')"})
        assert "python" in result.profile.languages

    def test_detects_javascript(self):
        result = profile_repository({"index.js": "const x = 1;"})
        assert "javascript" in result.profile.languages

    def test_detects_typescript(self):
        result = profile_repository({"app.ts": "const x: number = 1;"})
        assert "typescript" in result.profile.languages

    def test_detects_go(self):
        result = profile_repository({"main.go": "package main"})
        assert "go" in result.profile.languages

    def test_detects_multiple_languages(self):
        result = profile_repository({
            "app.py": "x = 1",
            "index.js": "y = 2",
            "main.go": "z",
        })
        assert "python" in result.profile.languages
        assert "javascript" in result.profile.languages
        assert "go" in result.profile.languages

    def test_detects_framework_by_filename(self):
        result = profile_repository({"requirements.txt": "flask==2.0"})
        assert "python-pip" in result.profile.frameworks

    def test_detects_node_framework(self):
        result = profile_repository({"package.json": '{"name": "app"}'})
        assert "node" in result.profile.frameworks

    def test_detects_docker(self):
        result = profile_repository({"Dockerfile": "FROM python:3.11"})
        assert "docker" in result.profile.frameworks

    def test_detects_fastapi_by_content(self):
        result = profile_repository({
            "app.py": "from fastapi import FastAPI\napp = FastAPI()"
        })
        assert "fastapi" in result.profile.frameworks

    def test_detects_flask_by_content(self):
        result = profile_repository({
            "app.py": "from flask import Flask\napp = Flask(__name__)"
        })
        assert "flask" in result.profile.frameworks

    def test_detects_django_by_content(self):
        result = profile_repository({
            "settings.py": "from django.conf import settings"
        })
        assert "django" in result.profile.frameworks

    def test_detects_sensitive_auth_path(self):
        result = profile_repository({"src/auth/login.py": "def login(): pass"})
        assert "src/auth/login.py" in result.profile.sensitive_paths

    def test_detects_sensitive_admin_path(self):
        result = profile_repository({"admin/panel.py": "x = 1"})
        assert "admin/panel.py" in result.profile.sensitive_paths

    def test_detects_sensitive_config_path(self):
        result = profile_repository({"config/settings.py": "SECRET = 'x'"})
        assert "config/settings.py" in result.profile.sensitive_paths

    def test_ignores_non_sensitive_paths(self):
        result = profile_repository({"src/utils.py": "def helper(): pass"})
        assert result.profile.sensitive_paths == []

    def test_detects_jwt_auth_pattern(self):
        result = profile_repository({
            "auth.py": "import jwt\ntoken = jwt.encode(payload, secret)"
        })
        assert any("JWT" in p for p in result.profile.auth_patterns)

    def test_detects_oauth_pattern(self):
        result = profile_repository({
            "auth.py": "from oauth2 import Client"
        })
        assert any("OAuth" in p for p in result.profile.auth_patterns)

    def test_detects_password_handling(self):
        result = profile_repository({
            "users.py": "def verify_password(plain, hashed): pass"
        })
        assert any("Password" in p for p in result.profile.auth_patterns)

    def test_no_auth_patterns_in_clean_file(self):
        result = profile_repository({
            "utils.py": "def add(a, b): return a + b"
        })
        assert result.profile.auth_patterns == []

    def test_notes_contain_file_count(self):
        result = profile_repository({"a.py": "x", "b.py": "y"})
        assert any("2 file(s)" in n for n in result.notes)

    def test_repo_name_propagated(self):
        result = profile_repository({"a.py": "x"}, repo="org/repo")
        assert result.profile.repo == "org/repo"


# ======================================================================
# Engine accepts PullRequestContext — integration smoke tests
# ======================================================================


class TestEngineAcceptsPullRequestContext:
    """Verify the engine accepts PullRequestContext alongside PRContent and dict."""

    def test_engine_accepts_pull_request_context(self):
        from reviewer.engine import analyse
        ctx = PullRequestContext.from_dict({"app.py": "x = 1"})
        result = analyse(ctx)
        assert isinstance(result.findings, list)
        assert isinstance(result.reasoning_notes, list)

    def test_engine_accepts_pr_content(self):
        from reviewer.engine import analyse
        pr = PRContent.from_dict({"app.py": "x = 1"})
        result = analyse(pr)
        assert isinstance(result.findings, list)

    def test_engine_accepts_dict(self):
        from reviewer.engine import analyse
        result = analyse({"app.py": "x = 1"})
        assert isinstance(result.findings, list)

    def test_engine_with_context_and_baseline(self):
        from reviewer.engine import analyse
        profile = RepoSecurityProfile(repo="acme/webapp", languages=["python"])
        ctx = PullRequestContext(
            pr_content=PRContent.from_dict({"app.py": "DEBUG = True"}),
            baseline_profile=profile,
        )
        result = analyse(ctx)
        # Deterministic checks should still fire
        assert len(result.findings) >= 1

    def test_engine_with_context_finds_insecure_patterns(self):
        from reviewer.engine import analyse
        ctx = PullRequestContext.from_dict({
            "server.py": 'app.add_middleware(CORSMiddleware, allow_origins=["*"])'
        })
        result = analyse(ctx)
        assert len(result.findings) >= 1
        assert any(f.title for f in result.findings if "CORS" in f.title)
