"""Ingestion endpoint for parity-zero scan results.

Accepts a structured ScanResult payload (the core JSON contract) and
validates it against the Pydantic schema.

Phase 1: validation only — the endpoint acknowledges receipt but does
not persist to a database.  Postgres storage will be wired in Phase 2.

See architecture.md § Central Ingestion API for responsibilities.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from schemas.findings import ScanResult

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ingest", status_code=202)
async def ingest_scan(result: ScanResult) -> dict:
    """Receive and validate a scan result.

    FastAPI + Pydantic perform automatic payload validation via the
    ``ScanResult`` type annotation.  Malformed payloads receive a 422
    response with validation details.

    Args:
        result: A ScanResult payload conforming to the findings schema.

    Returns:
        Acknowledgement with the scan_id, decision, risk_score, and
        findings_count.

    TODO:
        - Persist the result to Postgres (Phase 2).
        - Add authentication / API key validation.
    """
    logger.info(
        "Ingested scan %s: %d finding(s), decision=%s, risk=%d",
        result.scan_id,
        len(result.findings),
        result.decision.value,
        result.risk_score,
    )

    return {
        "status": "accepted",
        "scan_id": result.scan_id,
        "decision": result.decision.value,
        "risk_score": result.risk_score,
        "findings_count": len(result.findings),
    }
