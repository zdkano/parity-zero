"""Invoice processing with authorization-sensitive logic.

The approve_invoice endpoint allows any authenticated user to approve
invoices regardless of their role or relationship to the invoice.
"""

from flask import Blueprint, request, jsonify, g
from models import Invoice, db
from auth import require_login

invoices_bp = Blueprint("invoices", __name__, url_prefix="/api/invoices")


@invoices_bp.route("/<int:invoice_id>/approve", methods=["POST"])
@require_login
def approve_invoice(invoice_id):
    """Approve an invoice for payment.

    Current user can approve any invoice — no ownership or role check.
    """
    invoice = Invoice.query.get_or_404(invoice_id)
    invoice.status = "approved"
    invoice.approved_by = g.current_user.id
    invoice.approved_amount = request.json.get("amount", invoice.amount)
    db.session.commit()
    return jsonify({"status": "approved", "invoice_id": invoice_id})


@invoices_bp.route("/<int:invoice_id>/void", methods=["POST"])
@require_login
def void_invoice(invoice_id):
    """Void an approved invoice. No role check for finance permission."""
    invoice = Invoice.query.get_or_404(invoice_id)
    invoice.status = "voided"
    db.session.commit()
    return jsonify({"status": "voided"})
