"""Company-scoped API endpoints.

Every route derives the company id from the authenticated session via
:func:`current_company_id`. No request parameter, header or body value is ever
used to select a tenant, so a caller cannot reach another company's data by
guessing an id or supplying `company_id`.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from security.decorators import company_required, current_company_id
from services.customer_service import (
    company_analytics,
    company_customer_detail,
    company_customers,
    company_stats,
)

company_bp = Blueprint("company_api", __name__, url_prefix="/api/company")


def _failure(status: int, code: str, message: str, details=None):
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    return jsonify({"success": False, "error": error}), status


@company_bp.route("/stats")
@company_required
def company_api_stats():
    """KPI figures for the authenticated user's company only."""
    return jsonify({
        "success": True,
        "scope": "company",
        "stats": company_stats(current_company_id()),
    }), 200


@company_bp.route("/analytics")
@company_required
def company_api_analytics():
    """Chart aggregations for the authenticated user's company only."""
    return jsonify({
        "success": True,
        "scope": "company",
        "analytics": company_analytics(current_company_id()),
    }), 200


@company_bp.route("/customers")
@company_required
def company_api_customers():
    """Paginated, searchable customer list scoped to one company."""
    result = company_customers(
        current_company_id(),
        search=request.args.get("search", ""),
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 20, type=int),
        sort=request.args.get("sort", "customer_id"),
        order=request.args.get("order", "asc"),
        churn=request.args.get("churn", ""),
    )
    return jsonify({"success": True, "scope": "company", **result}), 200


@company_bp.route("/customers/<customer_id>")
@company_required
def company_api_customer_detail(customer_id: str):
    """One customer, but only if it belongs to the caller's company.

    A record owned by another company yields 404, not 403: confirming that an
    id exists elsewhere would itself leak information.
    """
    record = company_customer_detail(current_company_id(), customer_id)
    if record is None:
        return _failure(404, "NOT_FOUND", "No such customer in your company.")
    return jsonify({"success": True, "scope": "company", "customer": record}), 200
