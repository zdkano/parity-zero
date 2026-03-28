"""Bearer token authentication for the parity-zero backend API.

Provides a simple shared-token auth model suitable for Phase 2.
The token is configured via the ``PARITY_ZERO_AUTH_TOKEN`` environment
variable.

This is intentionally minimal — no user accounts, OAuth, RBAC, or SSO.
See ADR-035 for rationale and deferred concerns.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


def _get_configured_token() -> str:
    """Return the configured auth token, or empty string if unset."""
    return os.getenv("PARITY_ZERO_AUTH_TOKEN", "")


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency that enforces bearer token authentication.

    Reads the expected token from ``PARITY_ZERO_AUTH_TOKEN``.  If the env
    var is not set, **all requests are rejected** — an operator must
    explicitly configure the token.

    Returns:
        The validated token string.

    Raises:
        HTTPException 401: If the token is missing, empty, or does not match.
    """
    expected = _get_configured_token()

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Server auth token not configured (PARITY_ZERO_AUTH_TOKEN).",
        )

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    if not secrets.compare_digest(credentials.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )

    return credentials.credentials
