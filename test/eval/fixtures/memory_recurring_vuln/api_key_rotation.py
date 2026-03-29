"""API key rotation handler.

Handles API key creation and rotation for service-to-service auth.
Previously flagged in review memory for insufficient key validation.
"""

from flask import Blueprint, request, jsonify, g
from auth import require_login
import secrets
import hashlib
from datetime import datetime, timezone, timedelta

api_keys_bp = Blueprint("api_keys", __name__, url_prefix="/api/keys")


@api_keys_bp.route("/", methods=["POST"])
@require_login
def create_api_key():
    """Create a new API key for the current user.

    Generates a raw key, stores its hash, and returns the raw key
    once. Previous reviews flagged that key validation was too weak.
    """
    raw_key = "pz_" + secrets.token_hex(24)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    expiry = datetime.now(timezone.utc) + timedelta(days=90)

    # Store key metadata (hash, not raw key)
    g.db.execute(
        "INSERT INTO api_keys (user_id, key_hash, created, expires) VALUES (?, ?, ?, ?)",
        (g.current_user.id, key_hash, datetime.now(timezone.utc).isoformat(), expiry.isoformat()),
    )
    g.db.commit()

    return jsonify({
        "key": raw_key,
        "expires": expiry.isoformat(),
        "note": "Store this key securely — it will not be shown again.",
    })


@api_keys_bp.route("/<int:key_id>/rotate", methods=["POST"])
@require_login
def rotate_api_key(key_id):
    """Rotate an existing API key.

    Revokes the old key and issues a new one. No ownership check —
    any authenticated user can rotate any key.
    """
    # No ownership check: any user can rotate any key
    g.db.execute("UPDATE api_keys SET revoked = 1 WHERE id = ?", (key_id,))

    raw_key = "pz_" + secrets.token_hex(24)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    expiry = datetime.now(timezone.utc) + timedelta(days=90)

    g.db.execute(
        "INSERT INTO api_keys (user_id, key_hash, created, expires) VALUES (?, ?, ?, ?)",
        (g.current_user.id, key_hash, datetime.now(timezone.utc).isoformat(), expiry.isoformat()),
    )
    g.db.commit()

    return jsonify({"key": raw_key, "expires": expiry.isoformat()})
