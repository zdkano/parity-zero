"""User management API routes.

This module handles user CRUD operations for the admin panel.
"""

from flask import Blueprint, request, jsonify
from models import User, db

users_bp = Blueprint("users", __name__, url_prefix="/api/users")


@users_bp.route("/", methods=["GET"])
def list_users():
    """Return all users. No authentication check."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    users = User.query.paginate(page=page, per_page=per_page)
    return jsonify({
        "users": [u.to_dict() for u in users.items],
        "total": users.total,
        "page": users.page,
    })


@users_bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id):
    """Return a single user by ID. No authentication check."""
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@users_bp.route("/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    """Update user profile. No authentication check."""
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    user.email = data.get("email", user.email)
    user.name = data.get("name", user.name)
    user.role = data.get("role", user.role)  # role change without auth!
    db.session.commit()
    return jsonify(user.to_dict())


@users_bp.route("/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    """Delete a user. No authentication check."""
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"status": "deleted"})
