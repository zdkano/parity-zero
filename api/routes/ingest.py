"""Ingestion endpoint for parity-zero scan results.

Accepts a structured ScanResult payload (the core JSON contract),
validates it against the Pydantic schema, authenticates the request,
and persists the result to the SQLite store.

The endpoint also accepts optional run summary metadata fields that are
not part of the ScanResult contract but are useful for debugging and
history.  These are passed through to persistence alongside the core
fields.  See ADR-036 for the storage-shape evolution decisions.

See ADR-035 for the persistence and auth decisions.
See architecture.md § Central Ingestion API for responsibilities.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from schemas.findings import ScanResult

from api.auth import require_auth
from api.persistence import ScanStore

logger = logging.getLogger(__name__)

router = APIRouter()

# Run summary metadata keys accepted alongside the ScanResult fields.
# These are not part of the ScanResult JSON contract but are persisted
# for debugging and history.  See ADR-036.
_RUN_SUMMARY_KEYS = frozenset({
    "provider_name",
    "provider_invoked",
    "provider_gate_decision",
    "concerns_count",
    "observations_count",
    "provider_notes_count",
    "provider_notes_suppressed_count",
    "changed_files_count",
    "skipped_files_count",
})


def _get_store() -> ScanStore:
    """Provide the default ScanStore instance.

    Overridable via FastAPI dependency injection in tests.
    """
    return ScanStore()


@router.post("/ingest", status_code=202)
async def ingest_scan(
    request: Request,
    result: ScanResult,
    _token: str = Depends(require_auth),
    store: ScanStore = Depends(_get_store),
) -> dict:
    """Receive, validate, authenticate, and persist a scan result.

    FastAPI + Pydantic perform automatic payload validation via the
    ``ScanResult`` type annotation.  Malformed payloads receive a 422
    response with validation details.  Missing or invalid auth tokens
    receive a 401 response.

    In addition to the ScanResult fields, the endpoint accepts optional
    run summary metadata (e.g. ``provider_invoked``, ``concerns_count``,
    ``changed_files_count``).  These are persisted alongside the core
    fields for debugging and history.

    Args:
        result: A ScanResult payload conforming to the findings schema.

    Returns:
        Acknowledgement with the scan_id, decision, risk_score, and
        findings_count.
    """
    payload = result.model_dump(mode="json")

    # Merge run summary metadata from the raw request body into the
    # payload dict.  ScanResult validation has already succeeded, so
    # these extra fields are safe to pass through to persistence.
    try:
        raw_body = await request.json()
        if isinstance(raw_body, dict):
            for key in _RUN_SUMMARY_KEYS:
                if key in raw_body and key not in payload:
                    payload[key] = raw_body[key]
    except Exception:
        pass  # If raw body parsing fails, proceed without extra metadata

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
