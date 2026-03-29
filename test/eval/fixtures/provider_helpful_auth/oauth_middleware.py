"""OAuth2 token validation and session management middleware.

Complex authentication middleware that validates OAuth2 tokens,
manages session state, and enforces token expiry. This is the kind
of code where provider reasoning can add contextual value beyond
what deterministic checks detect.
"""

from functools import wraps
from datetime import datetime, timezone
from flask import request, g, abort, current_app
import jwt
import hashlib


def validate_oauth_token(token: str) -> dict | None:
    """Validate an OAuth2 bearer token and return claims.

    Decodes the JWT token using the app's public key. Returns the
    decoded payload or None if validation fails.
    """
    try:
        payload = jwt.decode(
            token,
            current_app.config["JWT_PUBLIC_KEY"],
            algorithms=["RS256"],
            audience=current_app.config["JWT_AUDIENCE"],
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_oauth(f):
    """Decorator that enforces OAuth2 authentication.

    Extracts the bearer token from the Authorization header,
    validates it, and populates g.current_user.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            abort(401)

        token = auth_header[7:]
        claims = validate_oauth_token(token)

        if claims is None:
            abort(401)

        # Check token expiry (additional check beyond JWT library)
        exp = claims.get("exp", 0)
        if datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
            abort(401)

        g.current_user = claims
        g.token_hash = hashlib.sha256(token.encode()).hexdigest()[:12]

        return f(*args, **kwargs)
    return decorated


def require_scope(scope: str):
    """Decorator that checks for a specific OAuth scope.

    Must be used after @require_oauth.
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            scopes = g.current_user.get("scope", "").split()
            if scope not in scopes:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


class SessionManager:
    """Server-side session management with token binding.

    Sessions are bound to token hashes to detect token reuse
    after rotation.
    """

    def __init__(self, store):
        self._store = store

    def create_session(self, user_id: str, token_hash: str) -> str:
        """Create a new session tied to a token hash."""
        session_id = hashlib.sha256(
            f"{user_id}:{token_hash}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()
        self._store.set(session_id, {
            "user_id": user_id,
            "token_hash": token_hash,
            "created": datetime.now(timezone.utc).isoformat(),
        })
        return session_id

    def validate_session(self, session_id: str, token_hash: str) -> bool:
        """Validate session exists and token hash matches."""
        data = self._store.get(session_id)
        if data is None:
            return False
        return data.get("token_hash") == token_hash

    def revoke_session(self, session_id: str):
        """Revoke a session."""
        self._store.delete(session_id)
