"""Ingestion endpoint for parity-zero scan results.

Accepts a structured ScanResult payload (the core JSON contract) and
validates it against the Pydantic schema.

Phase 1: validation only — the endpoint acknowledges receipt but does
not persist to a database.  Postgres storage will be wired in Phase 2.

See architecture.md § Central Ingestion API for responsibilities.
"""

from __future__ import annotations

from fastapi import APIRouter
from schemas.findings import ScanResult

router = APIRouter()


@router.post("/ingest", status_code=202)
async def ingest_scan(result: ScanResult) -> dict:
    """Receive and validate a scan result.

    Args:
        result: A ScanResult payload conforming to the findings schema.

    Returns:
        Acknowledgement with the scan_id.

    TODO:
        - Persist the result to Postgres (Phase 2).
        - Add authentication / API key validation.
    """
    # Pydantic validation happens automatically via the type annotation.
    # Phase 1: log / acknowledge only.
    return {
        "status": "accepted",
        "scan_id": result.scan_id,
        "findings_count": len(result.findings),
    }
