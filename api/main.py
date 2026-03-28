"""FastAPI application entry point for parity-zero ingestion API.

Provides:
  - Health check endpoint (unauthenticated)
  - Scan result ingestion endpoint (POST /ingest, authenticated)
  - Run retrieval endpoints (GET /runs, GET /runs/{scan_id}, authenticated)
  - SQLite persistence via ScanStore
  - Bearer token authentication via PARITY_ZERO_AUTH_TOKEN

See ADR-005 for the FastAPI choice rationale and ADR-035 for the
persistence and auth decisions.
"""

from fastapi import FastAPI

from api.routes.ingest import router as ingest_router
from api.routes.runs import router as runs_router

app = FastAPI(
    title="parity-zero ingestion API",
    description="Central ingestion and retrieval endpoint for parity-zero scan results.",
    version="0.2.0",
)

app.include_router(ingest_router)
app.include_router(runs_router)


@app.get("/health")
async def health() -> dict:
    """Simple liveness check."""
    return {"status": "ok"}
