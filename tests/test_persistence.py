"""Tests for the ScanStore persistence layer.

Validates:
  - Schema creation
  - Run persistence and retrieval
  - Finding persistence
  - List/pagination
  - Edge cases (duplicate, missing fields)
  - Run summary metadata persistence (ADR-036)
"""

import pytest

from api.persistence import ScanStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store() -> ScanStore:
    return ScanStore(":memory:")


def _valid_run(**overrides) -> dict:
    run = {
        "scan_id": "a" * 32,
        "repo": "acme/webapp",
        "pr_number": 10,
        "commit_sha": "abc1234",
        "ref": "feature/auth",
        "timestamp": "2026-03-28T12:00:00+00:00",
        "decision": "warn",
        "risk_score": 25,
        "findings": [
            {
                "id": "f001",
                "category": "authentication",
                "severity": "high",
                "confidence": "medium",
                "title": "Missing auth",
                "description": "Admin route unprotected.",
                "file": "src/admin.py",
                "start_line": 15,
                "end_line": 20,
                "recommendation": "Add auth middleware.",
            }
        ],
    }
    run.update(overrides)
    return run


# ---------------------------------------------------------------------------
# Schema and lifecycle
# ---------------------------------------------------------------------------

class TestStoreLifecycle:
    def test_create_store(self):
        store = _make_store()
        assert store is not None
        store.close()

    def test_close_is_idempotent(self):
        store = _make_store()
        store.close()
        store.close()  # should not raise


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

class TestSaveRun:
    def test_save_run_returns_scan_id(self):
        store = _make_store()
        scan_id = store.save_run(_valid_run())
        assert scan_id == "a" * 32

    def test_save_run_persists_metadata(self):
        store = _make_store()
        store.save_run(_valid_run())
        run = store.get_run("a" * 32)
        assert run["repo"] == "acme/webapp"
        assert run["pr_number"] == 10
        assert run["decision"] == "warn"
        assert run["risk_score"] == 25

    def test_save_run_persists_findings(self):
        store = _make_store()
        store.save_run(_valid_run())
        run = store.get_run("a" * 32)
        assert len(run["findings"]) == 1
        assert run["findings"][0]["id"] == "f001"
        assert run["findings"][0]["category"] == "authentication"

    def test_save_run_no_findings(self):
        store = _make_store()
        store.save_run(_valid_run(findings=[]))
        run = store.get_run("a" * 32)
        assert run["findings"] == []
        assert run["findings_count"] == 0

    def test_save_run_multiple_findings(self):
        store = _make_store()
        findings = [
            {
                "id": f"f{i:03d}",
                "category": "secrets",
                "severity": "high",
                "confidence": "high",
                "title": f"Secret {i}",
                "description": f"Found secret {i}.",
                "file": f"src/file{i}.py",
                "start_line": i,
                "end_line": None,
                "recommendation": None,
            }
            for i in range(5)
        ]
        store.save_run(_valid_run(findings=findings))
        run = store.get_run("a" * 32)
        assert len(run["findings"]) == 5

    def test_save_run_missing_scan_id_raises(self):
        store = _make_store()
        with pytest.raises(ValueError):
            store.save_run({"repo": "x"})

    def test_save_duplicate_scan_id_raises(self):
        store = _make_store()
        store.save_run(_valid_run())
        with pytest.raises(Exception):  # sqlite3.IntegrityError
            store.save_run(_valid_run())

    def test_save_run_with_provider_name(self):
        store = _make_store()
        store.save_run(_valid_run(provider_name="github-models"))
        run = store.get_run("a" * 32)
        assert run["provider_name"] == "github-models"


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

class TestGetRun:
    def test_get_nonexistent_run_returns_none(self):
        store = _make_store()
        assert store.get_run("nonexistent") is None

    def test_get_run_includes_findings(self):
        store = _make_store()
        store.save_run(_valid_run())
        run = store.get_run("a" * 32)
        assert "findings" in run
        assert len(run["findings"]) == 1

    def test_get_findings_for_run(self):
        store = _make_store()
        store.save_run(_valid_run())
        findings = store.get_findings_for_run("a" * 32)
        assert len(findings) == 1
        assert findings[0]["title"] == "Missing auth"

    def test_get_findings_for_nonexistent_run(self):
        store = _make_store()
        findings = store.get_findings_for_run("nonexistent")
        assert findings == []


class TestListRuns:
    def test_list_empty(self):
        store = _make_store()
        assert store.list_runs() == []

    def test_list_after_save(self):
        store = _make_store()
        store.save_run(_valid_run())
        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0]["scan_id"] == "a" * 32

    def test_list_does_not_include_findings(self):
        store = _make_store()
        store.save_run(_valid_run())
        runs = store.list_runs()
        assert "findings" not in runs[0]

    def test_list_filter_by_repo(self):
        store = _make_store()
        store.save_run(_valid_run(scan_id="s1", repo="acme/webapp"))
        store.save_run(_valid_run(scan_id="s2", repo="other/repo"))
        runs = store.list_runs(repo="acme/webapp")
        assert len(runs) == 1
        assert runs[0]["repo"] == "acme/webapp"

    def test_list_limit(self):
        store = _make_store()
        for i in range(10):
            store.save_run(_valid_run(scan_id=f"s{i:04d}"))
        runs = store.list_runs(limit=3)
        assert len(runs) == 3

    def test_list_offset(self):
        store = _make_store()
        for i in range(5):
            store.save_run(_valid_run(scan_id=f"s{i:04d}"))
        all_runs = store.list_runs(limit=100)
        offset_runs = store.list_runs(limit=100, offset=3)
        assert len(offset_runs) == 2

    def test_list_limit_clamped_to_100(self):
        store = _make_store()
        # Just verify it doesn't error with limit > 100
        runs = store.list_runs(limit=200)
        assert isinstance(runs, list)


# ---------------------------------------------------------------------------
# Run summary metadata (ADR-036)
# ---------------------------------------------------------------------------

class TestRunSummaryMetadata:
    """Tests that run summary metadata fields persist and retrieve correctly."""

    def test_provider_invoked_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(provider_invoked=True))
        run = store.get_run("a" * 32)
        assert run["provider_invoked"] == 1

    def test_provider_invoked_defaults_to_false(self):
        store = _make_store()
        store.save_run(_valid_run())
        run = store.get_run("a" * 32)
        assert run["provider_invoked"] == 0

    def test_provider_gate_decision_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(provider_gate_decision="invoked"))
        run = store.get_run("a" * 32)
        assert run["provider_gate_decision"] == "invoked"

    def test_concerns_count_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(concerns_count=5))
        run = store.get_run("a" * 32)
        assert run["concerns_count"] == 5

    def test_observations_count_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(observations_count=3))
        run = store.get_run("a" * 32)
        assert run["observations_count"] == 3

    def test_provider_notes_count_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(provider_notes_count=8))
        run = store.get_run("a" * 32)
        assert run["provider_notes_count"] == 8

    def test_provider_notes_suppressed_count_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(provider_notes_suppressed_count=2))
        run = store.get_run("a" * 32)
        assert run["provider_notes_suppressed_count"] == 2

    def test_changed_files_count_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(changed_files_count=12))
        run = store.get_run("a" * 32)
        assert run["changed_files_count"] == 12

    def test_skipped_files_count_persisted(self):
        store = _make_store()
        store.save_run(_valid_run(skipped_files_count=3))
        run = store.get_run("a" * 32)
        assert run["skipped_files_count"] == 3

    def test_all_summary_metadata_defaults(self):
        store = _make_store()
        store.save_run(_valid_run())
        run = store.get_run("a" * 32)
        assert run["provider_invoked"] == 0
        assert run["provider_gate_decision"] == ""
        assert run["concerns_count"] == 0
        assert run["observations_count"] == 0
        assert run["provider_notes_count"] == 0
        assert run["provider_notes_suppressed_count"] == 0
        assert run["changed_files_count"] == 0
        assert run["skipped_files_count"] == 0

    def test_all_summary_metadata_with_values(self):
        store = _make_store()
        store.save_run(_valid_run(
            provider_name="anthropic",
            provider_invoked=True,
            provider_gate_decision="invoked",
            concerns_count=2,
            observations_count=4,
            provider_notes_count=6,
            provider_notes_suppressed_count=1,
            changed_files_count=15,
            skipped_files_count=3,
        ))
        run = store.get_run("a" * 32)
        assert run["provider_name"] == "anthropic"
        assert run["provider_invoked"] == 1
        assert run["provider_gate_decision"] == "invoked"
        assert run["concerns_count"] == 2
        assert run["observations_count"] == 4
        assert run["provider_notes_count"] == 6
        assert run["provider_notes_suppressed_count"] == 1
        assert run["changed_files_count"] == 15
        assert run["skipped_files_count"] == 3

    def test_summary_metadata_in_list_runs(self):
        store = _make_store()
        store.save_run(_valid_run(changed_files_count=10, skipped_files_count=2))
        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0]["changed_files_count"] == 10
        assert runs[0]["skipped_files_count"] == 2
