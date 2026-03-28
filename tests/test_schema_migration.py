"""Tests for lightweight SQLite schema migration (ADR-037).

Validates:
  - Old-schema databases are upgraded automatically when ScanStore opens
  - Fresh databases still work correctly (no regression)
  - Migration is idempotent (reopening the same DB is safe)
  - API/backend behaviour works correctly after upgrade
  - Migration adds the correct columns with safe defaults
  - Pre-existing rows in old-schema DBs get correct default values
"""

import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

from api.persistence import ScanStore, _migrate_runs_table, _ADDITIVE_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The old runs schema — matches what ADR-035 shipped before ADR-036 columns.
_OLD_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    scan_id     TEXT PRIMARY KEY,
    repo        TEXT NOT NULL,
    pr_number   INTEGER NOT NULL,
    commit_sha  TEXT NOT NULL,
    ref         TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    decision    TEXT NOT NULL,
    risk_score  INTEGER NOT NULL,
    findings_count INTEGER NOT NULL,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    id             TEXT NOT NULL,
    scan_id        TEXT NOT NULL,
    category       TEXT NOT NULL,
    severity       TEXT NOT NULL,
    confidence     TEXT NOT NULL,
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    file           TEXT NOT NULL,
    start_line     INTEGER,
    end_line       INTEGER,
    recommendation TEXT,
    PRIMARY KEY (id, scan_id),
    FOREIGN KEY (scan_id) REFERENCES runs(scan_id) ON DELETE CASCADE
);
"""


def _create_old_schema_db(path: str) -> None:
    """Create a SQLite DB with the old runs schema (pre-ADR-036)."""
    conn = sqlite3.connect(path)
    conn.executescript(_OLD_SCHEMA_SQL)
    conn.close()


def _insert_old_row(path: str, scan_id: str = "old-run-001") -> None:
    """Insert a run row into an old-schema DB (no ADR-036 columns)."""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        INSERT INTO runs
            (scan_id, repo, pr_number, commit_sha, ref, timestamp,
             decision, risk_score, findings_count, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scan_id, "acme/legacy", 1, "deadbeef", "main",
            "2026-01-01T00:00:00+00:00", "pass", 0, 0,
            "2026-01-01T00:00:01+00:00",
        ),
    )
    conn.commit()
    conn.close()


def _valid_run(**overrides) -> dict:
    run = {
        "scan_id": "new-run-001",
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


def _get_column_names(path: str, table: str = "runs") -> set[str]:
    """Return column names for the given table."""
    conn = sqlite3.connect(path)
    cursor = conn.execute(f"PRAGMA table_info({table})")
    names = {row[1] for row in cursor.fetchall()}
    conn.close()
    return names


# ---------------------------------------------------------------------------
# A. Old-schema upgrade test
# ---------------------------------------------------------------------------

class TestOldSchemaUpgrade:
    """Opening a ScanStore on an old-schema DB should migrate it."""

    def test_migration_adds_missing_columns(self, tmp_path):
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)

        # Verify old schema lacks the new columns
        old_cols = _get_column_names(db_path)
        for col_name, _, _ in _ADDITIVE_COLUMNS:
            assert col_name not in old_cols, f"{col_name} should not exist yet"

        # Open with ScanStore — migration should run
        store = ScanStore(db_path)
        store._connect()

        # Verify new columns exist
        new_cols = _get_column_names(db_path)
        for col_name, _, _ in _ADDITIVE_COLUMNS:
            assert col_name in new_cols, f"{col_name} should have been added"

        store.close()

    def test_save_run_after_upgrade(self, tmp_path):
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)

        store = ScanStore(db_path)
        scan_id = store.save_run(_valid_run())
        assert scan_id == "new-run-001"
        store.close()

    def test_retrieve_run_after_upgrade(self, tmp_path):
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)

        store = ScanStore(db_path)
        store.save_run(_valid_run(
            provider_invoked=True,
            provider_gate_decision="invoked",
            concerns_count=2,
            changed_files_count=5,
        ))
        run = store.get_run("new-run-001")
        assert run is not None
        assert run["repo"] == "acme/webapp"
        assert run["provider_invoked"] == 1
        assert run["provider_gate_decision"] == "invoked"
        assert run["concerns_count"] == 2
        assert run["changed_files_count"] == 5
        assert len(run["findings"]) == 1
        store.close()

    def test_pre_existing_rows_get_defaults(self, tmp_path):
        """Rows inserted before migration should get default values."""
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)
        _insert_old_row(db_path)

        store = ScanStore(db_path)
        run = store.get_run("old-run-001")
        assert run is not None
        assert run["repo"] == "acme/legacy"
        # New columns should have safe defaults
        assert run["provider_invoked"] == 0
        assert run["provider_gate_decision"] == ""
        assert run["concerns_count"] == 0
        assert run["observations_count"] == 0
        assert run["provider_notes_count"] == 0
        assert run["provider_notes_suppressed_count"] == 0
        assert run["changed_files_count"] == 0
        assert run["skipped_files_count"] == 0
        store.close()

    def test_pre_existing_rows_and_new_rows_coexist(self, tmp_path):
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)
        _insert_old_row(db_path, scan_id="legacy-001")

        store = ScanStore(db_path)
        store.save_run(_valid_run(scan_id="modern-001", changed_files_count=7))

        runs = store.list_runs()
        assert len(runs) == 2

        legacy = store.get_run("legacy-001")
        modern = store.get_run("modern-001")
        assert legacy["changed_files_count"] == 0  # default
        assert modern["changed_files_count"] == 7   # explicit
        store.close()

    def test_list_runs_after_upgrade(self, tmp_path):
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)
        _insert_old_row(db_path)

        store = ScanStore(db_path)
        runs = store.list_runs()
        assert len(runs) == 1
        assert runs[0]["scan_id"] == "old-run-001"
        assert runs[0]["provider_invoked"] == 0
        store.close()


# ---------------------------------------------------------------------------
# B. Fresh DB behavior unchanged
# ---------------------------------------------------------------------------

class TestFreshDBUnchanged:
    """Fresh DBs should work exactly as before — no regression."""

    def test_fresh_in_memory_store(self):
        store = ScanStore(":memory:")
        store.save_run(_valid_run())
        run = store.get_run("new-run-001")
        assert run is not None
        assert run["repo"] == "acme/webapp"
        assert run["findings_count"] == 1
        store.close()

    def test_fresh_file_store(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        store = ScanStore(db_path)
        store.save_run(_valid_run())
        run = store.get_run("new-run-001")
        assert run is not None
        assert run["provider_invoked"] == 0
        assert run["changed_files_count"] == 0
        store.close()

    def test_fresh_store_has_all_columns(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")
        store = ScanStore(db_path)
        store._connect()
        cols = _get_column_names(db_path)
        for col_name, _, _ in _ADDITIVE_COLUMNS:
            assert col_name in cols
        store.close()


# ---------------------------------------------------------------------------
# C. Migration idempotence
# ---------------------------------------------------------------------------

class TestMigrationIdempotence:
    """Reopening the same DB multiple times should be safe."""

    def test_reopen_old_db_twice(self, tmp_path):
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)

        # First open — triggers migration
        store1 = ScanStore(db_path)
        store1.save_run(_valid_run(scan_id="run-1"))
        store1.close()

        # Second open — should not fail
        store2 = ScanStore(db_path)
        store2.save_run(_valid_run(scan_id="run-2"))
        runs = store2.list_runs()
        assert len(runs) == 2
        store2.close()

    def test_reopen_fresh_db_twice(self, tmp_path):
        db_path = str(tmp_path / "fresh.db")

        store1 = ScanStore(db_path)
        store1.save_run(_valid_run(scan_id="run-1"))
        store1.close()

        store2 = ScanStore(db_path)
        store2.save_run(_valid_run(scan_id="run-2"))
        runs = store2.list_runs()
        assert len(runs) == 2
        store2.close()

    def test_reopen_three_times(self, tmp_path):
        db_path = str(tmp_path / "reopen.db")
        _create_old_schema_db(db_path)

        for i in range(3):
            store = ScanStore(db_path)
            store.save_run(_valid_run(scan_id=f"run-{i}"))
            store.close()

        store = ScanStore(db_path)
        runs = store.list_runs()
        assert len(runs) == 3
        store.close()

    def test_migrate_runs_table_direct_idempotence(self, tmp_path):
        """Calling _migrate_runs_table multiple times is safe."""
        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)

        conn = sqlite3.connect(db_path)
        _migrate_runs_table(conn)
        _migrate_runs_table(conn)  # second call should be no-op
        _migrate_runs_table(conn)  # third call should be no-op

        cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        for col_name, _, _ in _ADDITIVE_COLUMNS:
            assert col_name in cols
        conn.close()


# ---------------------------------------------------------------------------
# D. API/backend behavior after upgrade
# ---------------------------------------------------------------------------

class TestAPIAfterUpgrade:
    """API endpoints should work on an upgraded database."""

    def test_ingest_into_upgraded_db(self, tmp_path):
        from api.main import app
        from api.auth import require_auth
        from api.routes.ingest import _get_store as ingest_get_store
        from api.routes.runs import _get_store as runs_get_store

        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)
        _insert_old_row(db_path)

        store = ScanStore(db_path)

        app.dependency_overrides[ingest_get_store] = lambda: store
        app.dependency_overrides[runs_get_store] = lambda: store
        app.dependency_overrides[require_auth] = lambda: "test-token"

        try:
            client = TestClient(app)

            # Ingest a new run into the upgraded DB
            resp = client.post("/ingest", json={
                "repo": "acme/webapp",
                "pr_number": 42,
                "commit_sha": "abc1234",
                "ref": "feature/auth",
                "findings": [],
                "provider_invoked": True,
                "provider_gate_decision": "invoked",
                "changed_files_count": 10,
            })
            assert resp.status_code == 202
            body = resp.json()
            assert body["status"] == "accepted"
            scan_id = body["scan_id"]

            # Retrieve the ingested run
            resp = client.get(f"/runs/{scan_id}")
            assert resp.status_code == 200
            run = resp.json()
            assert run["provider_invoked"] == 1
            assert run["provider_gate_decision"] == "invoked"
            assert run["changed_files_count"] == 10

            # Legacy run should still be retrievable
            resp = client.get("/runs/old-run-001")
            assert resp.status_code == 200
            legacy = resp.json()
            assert legacy["repo"] == "acme/legacy"
            assert legacy["provider_invoked"] == 0
            assert legacy["changed_files_count"] == 0

            # List should show both
            resp = client.get("/runs")
            assert resp.status_code == 200
            assert resp.json()["count"] == 2

        finally:
            app.dependency_overrides.pop(ingest_get_store, None)
            app.dependency_overrides.pop(runs_get_store, None)
            app.dependency_overrides.pop(require_auth, None)
            store.close()

    def test_retrieval_endpoints_on_upgraded_db(self, tmp_path):
        from api.main import app
        from api.auth import require_auth
        from api.routes.ingest import _get_store as ingest_get_store
        from api.routes.runs import _get_store as runs_get_store

        db_path = str(tmp_path / "old.db")
        _create_old_schema_db(db_path)
        _insert_old_row(db_path, scan_id="legacy-run")

        store = ScanStore(db_path)

        app.dependency_overrides[ingest_get_store] = lambda: store
        app.dependency_overrides[runs_get_store] = lambda: store
        app.dependency_overrides[require_auth] = lambda: "test-token"

        try:
            client = TestClient(app)

            # List runs — legacy data should be visible with defaults
            resp = client.get("/runs")
            assert resp.status_code == 200
            runs = resp.json()["runs"]
            assert len(runs) == 1
            assert runs[0]["provider_invoked"] == 0
            assert runs[0]["changed_files_count"] == 0
            assert runs[0]["skipped_files_count"] == 0

            # Get single run
            resp = client.get("/runs/legacy-run")
            assert resp.status_code == 200
            run = resp.json()
            assert run["scan_id"] == "legacy-run"
            assert run["concerns_count"] == 0
            assert run["observations_count"] == 0

        finally:
            app.dependency_overrides.pop(ingest_get_store, None)
            app.dependency_overrides.pop(runs_get_store, None)
            app.dependency_overrides.pop(require_auth, None)
            store.close()


# ---------------------------------------------------------------------------
# E. Migration helper unit tests
# ---------------------------------------------------------------------------

class TestMigrateRunsTableHelper:
    """Direct tests for the _migrate_runs_table helper function."""

    def test_no_op_on_current_schema(self, tmp_path):
        """No changes when schema is already current."""
        db_path = str(tmp_path / "current.db")
        conn = sqlite3.connect(db_path)
        from api.persistence import _SCHEMA_SQL
        conn.executescript(_SCHEMA_SQL)

        before_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        _migrate_runs_table(conn)
        after_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}

        assert before_cols == after_cols
        conn.close()

    def test_adds_only_missing_columns(self, tmp_path):
        """If some columns exist and some don't, only missing ones are added."""
        db_path = str(tmp_path / "partial.db")
        conn = sqlite3.connect(db_path)
        # Create old schema
        conn.executescript(_OLD_SCHEMA_SQL)
        # Manually add just provider_name
        conn.execute("ALTER TABLE runs ADD COLUMN provider_name TEXT NOT NULL DEFAULT ''")

        before_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "provider_name" in before_cols
        assert "provider_invoked" not in before_cols

        _migrate_runs_table(conn)

        after_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        for col_name, _, _ in _ADDITIVE_COLUMNS:
            assert col_name in after_cols
        conn.close()
