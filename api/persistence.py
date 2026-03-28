"""SQLite persistence layer for parity-zero scan results.

Provides minimal storage for review results received through the ingest API.
Uses SQLite for Phase 2 simplicity — zero external dependencies, easy local
setup, and low operational burden.

Migration to Postgres or another store is expected in later phases as query
and reporting needs grow.  See ADR-035.

Schema:
  - ``runs`` — scan-level metadata (one row per ingest)
  - ``findings`` — individual findings linked to a run

The module exposes a ``ScanStore`` class that manages database lifecycle,
schema initialisation, and CRUD operations.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default database path — overridable via PARITY_ZERO_DB_PATH env var.
_DEFAULT_DB_PATH = "parity_zero.db"

_SCHEMA_SQL = """
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
    provider_name TEXT NOT NULL DEFAULT '',
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

CREATE INDEX IF NOT EXISTS idx_findings_scan_id ON findings(scan_id);
CREATE INDEX IF NOT EXISTS idx_runs_repo ON runs(repo);
CREATE INDEX IF NOT EXISTS idx_runs_ingested_at ON runs(ingested_at);
"""


class ScanStore:
    """Minimal SQLite store for persisted scan results.

    Usage::

        store = ScanStore()           # uses PARITY_ZERO_DB_PATH or default
        store = ScanStore(":memory:") # in-memory for tests

    The store creates tables on first use and is safe for single-writer
    concurrent reads (SQLite default).
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or os.getenv("PARITY_ZERO_DB_PATH", _DEFAULT_DB_PATH)
        self._conn: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA_SQL)
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_run(self, payload: dict[str, Any]) -> str:
        """Persist a scan result payload.

        Args:
            payload: A dict matching the ScanResult JSON shape.

        Returns:
            The ``scan_id`` of the persisted run.

        Raises:
            ValueError: If required fields are missing.
            sqlite3.IntegrityError: If the scan_id already exists.
        """
        conn = self._connect()

        scan_id = payload.get("scan_id", "")
        if not scan_id:
            raise ValueError("scan_id is required")

        ingested_at = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO runs
                (scan_id, repo, pr_number, commit_sha, ref, timestamp,
                 decision, risk_score, findings_count, provider_name, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                payload.get("repo", ""),
                payload.get("pr_number", 0),
                payload.get("commit_sha", ""),
                payload.get("ref", ""),
                payload.get("timestamp", ingested_at),
                payload.get("decision", "pass"),
                payload.get("risk_score", 0),
                len(payload.get("findings", [])),
                payload.get("provider_name", ""),
                ingested_at,
            ),
        )

        for f in payload.get("findings", []):
            conn.execute(
                """
                INSERT INTO findings
                    (id, scan_id, category, severity, confidence, title,
                     description, file, start_line, end_line, recommendation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f.get("id", ""),
                    scan_id,
                    f.get("category", ""),
                    f.get("severity", ""),
                    f.get("confidence", ""),
                    f.get("title", ""),
                    f.get("description", ""),
                    f.get("file", ""),
                    f.get("start_line"),
                    f.get("end_line"),
                    f.get("recommendation"),
                ),
            )

        conn.commit()
        logger.info("Persisted run %s (%d findings)", scan_id, len(payload.get("findings", [])))
        return scan_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_run(self, scan_id: str) -> dict[str, Any] | None:
        """Retrieve a run by scan_id, including its findings.

        Returns None if the run does not exist.
        """
        conn = self._connect()

        row = conn.execute("SELECT * FROM runs WHERE scan_id = ?", (scan_id,)).fetchone()
        if row is None:
            return None

        run = dict(row)
        findings_rows = conn.execute(
            "SELECT * FROM findings WHERE scan_id = ? ORDER BY rowid",
            (scan_id,),
        ).fetchall()
        run["findings"] = [dict(r) for r in findings_rows]
        return run

    def list_runs(
        self,
        repo: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List recent runs, optionally filtered by repo.

        Args:
            repo: Optional repository filter (exact match).
            limit: Maximum number of results (default 20, max 100).
            offset: Pagination offset.

        Returns:
            List of run dicts (without findings — use ``get_run`` for full detail).
        """
        conn = self._connect()
        limit = min(max(limit, 1), 100)
        offset = max(offset, 0)

        if repo:
            rows = conn.execute(
                "SELECT * FROM runs WHERE repo = ? ORDER BY ingested_at DESC LIMIT ? OFFSET ?",
                (repo, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY ingested_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        return [dict(r) for r in rows]

    def get_findings_for_run(self, scan_id: str) -> list[dict[str, Any]]:
        """Retrieve findings for a specific run.

        Returns an empty list if the run does not exist.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM findings WHERE scan_id = ? ORDER BY rowid",
            (scan_id,),
        ).fetchall()
        return [dict(r) for r in rows]
