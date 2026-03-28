"""Retrieval endpoints for persisted scan runs.

Provides minimal read access for debugging and validation:
  - ``GET /runs``          — list recent runs
  - ``GET /runs/{scan_id}`` — get a single run with findings

All endpoints require bearer token authentication.
See ADR-035 for scope and deferred concerns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_auth
from api.persistence import ScanStore

router = APIRouter()


def _get_store() -> ScanStore:
    """Provide the default ScanStore instance.

    Overridable via FastAPI dependency injection in tests.
    """
    return ScanStore()


@router.get("/runs")
async def list_runs(
    repo: str | None = Query(None, description="Filter by repository (exact match)."),
    limit: int = Query(20, ge=1, le=100, description="Max results."),
    offset: int = Query(0, ge=0, description="Pagination offset."),
    _token: str = Depends(require_auth),
    store: ScanStore = Depends(_get_store),
) -> dict:
    """List recent scan runs.

    Returns run metadata without findings.  Use ``GET /runs/{scan_id}``
    for full detail.
    """
    runs = store.list_runs(repo=repo, limit=limit, offset=offset)
    return {"runs": runs, "count": len(runs)}


@router.get("/runs/{scan_id}")
async def get_run(
    scan_id: str,
    _token: str = Depends(require_auth),
    store: ScanStore = Depends(_get_store),
) -> dict:
    """Retrieve a single run by scan_id, including its findings."""
    run = store.get_run(scan_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run
