"""Product search with direct SQL query construction.

Demonstrates unsafe input handling — user input interpolated directly
into SQL queries without parameterization.
"""

from flask import Blueprint, request, jsonify
import sqlite3

search_bp = Blueprint("search", __name__, url_prefix="/api/search")

DB_PATH = "app.db"


@search_bp.route("/products", methods=["GET"])
def search_products():
    """Search products by name. User input goes directly into SQL."""
    query = request.args.get("q", "")
    sort_by = request.args.get("sort", "name")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Unsafe: direct string interpolation in SQL
    sql = f"SELECT id, name, price FROM products WHERE name LIKE '%{query}%' ORDER BY {sort_by}"
    cursor.execute(sql)
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "name": r[1], "price": r[2]} for r in rows])


@search_bp.route("/users", methods=["GET"])
def search_users():
    """Search users by email. Also uses unsafe string formatting."""
    email = request.args.get("email", "")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(f"SELECT id, name, email FROM users WHERE email = '{email}'")
    rows = cursor.fetchall()
    conn.close()
    return jsonify([{"id": r[0], "name": r[1], "email": r[2]} for r in rows])
