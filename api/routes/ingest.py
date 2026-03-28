"""Ingestion endpoint for parity-zero scan results.

Accepts a structured ScanResult payload (the core JSON contract),
validates it against the Pydantic schema, authenticates the request,
and persists the result to the SQLite store.

See ADR-035 for the persistence and auth decisions.
See architecture.md § Central Ingestion API for responsibilities.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from schemas.findings import ScanResult

from api.auth import require_auth
from api.persistence import ScanStore

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_store() -> ScanStore:
    """Provide the default ScanStore instance.

    Overridable via FastAPI dependency injection in tests.
    """
    return ScanStore()


@router.post("/ingest", status_code=202)
async def ingest_scan(
    result: ScanResult,
    _token: str = Depends(require_auth),
    store: ScanStore = Depends(_get_store),
) -> dict:
    """Receive, validate, authenticate, and persist a scan result.

    FastAPI + Pydantic perform automatic payload validation via the
    ``ScanResult`` type annotation.  Malformed payloads receive a 422
    response with validation details.  Missing or invalid auth tokens
    receive a 401 response.

    Args:
        result: A ScanResult payload conforming to the findings schema.

    Returns:
        Acknowledgement with the scan_id, decision, risk_score, and
        findings_count.
    """
    payload = result.model_dump(mode="json")
    scan_id = store.save_run(payload)

    logger.info(
        "Ingested scan %s: %d finding(s), decision=%s, risk=%d",
        scan_id,
        len(result.findings),
        result.decision.value,
        result.risk_score,
    )

    return {
        "status": "accepted",
        "scan_id": scan_id,
        "decision": result.decision.value,
        "risk_score": result.risk_score,
        "findings_count": len(result.findings),
    }
