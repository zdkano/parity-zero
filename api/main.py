"""FastAPI application entry point for parity-zero ingestion API.

Phase 1 scope (see roadmap.md):
  - Health check endpoint
  - Scan result ingestion endpoint (POST /ingest)
  - Payload validation via Pydantic (schemas.findings)
  - No persistence — storage will be added in Phase 2

See ADR-005 for the FastAPI choice rationale and ADR-006 for the
future Postgres store.
"""

from fastapi import FastAPI

from api.routes.ingest import router as ingest_router

app = FastAPI(
    title="parity-zero ingestion API",
    description="Central ingestion endpoint for parity-zero scan results.",
    version="0.1.0",
)

app.include_router(ingest_router)


@app.get("/health")
async def health() -> dict:
    """Simple liveness check."""
    return {"status": "ok"}
