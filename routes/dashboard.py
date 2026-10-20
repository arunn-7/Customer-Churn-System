"""Dashboard and customer-list endpoints (IBM SAMPLE / DEMO SCOPE).

Read-only JSON APIs backed by MySQL. Kept separate from `predict_bp` so the
prediction API contract stays exactly as it was.

SCOPE AND ACCESS POLICY
-----------------------
Everything here serves the IBM sample dataset, NOT any company's operational
data. Access requires authentication and a role permitted to view demo data
(Admin or Analyst). Viewer is refused by `demo_access_required`.

Company-owned records must never appear here, and IBM rows must never appear
in `/api/company/*`. The two scopes are physically separate query paths.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from security.decorators import demo_access_required
from services.customer_service import (
    analytics,
    find_customer,
    list_customers,
    stats,
)

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api")

DEMO_NOTICE = "IBM Sample Data - Demo Mode"


@dashboard_bp.route("/stats")
@demo_access_required
def api_stats():
    """Headline KPIs for the dashboard cards."""
    try:
        return jsonify({"success": True, "scope": "demo", "notice": DEMO_NOTICE,
                        "stats": stats()}), 200
    except Exception:
        logger.exception("Failed to load dashboard stats")
        return jsonify({
            "success": False,
            "error": {"code": "DATA_UNAVAILABLE", "message": "Could not load dashboard statistics."},
        }), 500


@dashboard_bp.route("/analytics")
@demo_access_required
def api_analytics():
    """Aggregations for the dashboard charts."""
    try:
        return jsonify({"success": True, "scope": "demo", "notice": DEMO_NOTICE,
                        "analytics": analytics()}), 200
    except Exception:
        logger.exception("Failed to load analytics")
        return jsonify({
            "success": False,
            "error": {"code": "DATA_UNAVAILABLE", "message": "Could not load analytics."},
        }), 500


@dashboard_bp.route("/customers")
@demo_access_required
def api_customers():
    """Paginated customer list with search, sort and churn filter."""
    try:
        result = list_customers(
            search=request.args.get("search", ""),
            page=request.args.get("page", 1, type=int),
            per_page=request.args.get("per_page", 20, type=int),
            sort=request.args.get("sort", "customer_id"),
            order=request.args.get("order", "asc"),
            churn=request.args.get("churn", ""),
        )
        return jsonify({"success": True, "scope": "demo", "notice": DEMO_NOTICE,
                        **result}), 200
    except Exception:
        logger.exception("Failed to load customers")
        return jsonify({
            "success": False,
            "error": {"code": "DATA_UNAVAILABLE", "message": "Could not load customers."},
        }), 500


@dashboard_bp.route("/customers/<customer_id>")
@demo_access_required
def api_customer_detail(customer_id: str):
    """A single sample customer by public id."""
    try:
        record = find_customer(customer_id)
    except Exception:
        logger.exception("Failed to load customer")
        return jsonify({
            "success": False,
            "error": {"code": "DATA_UNAVAILABLE", "message": "Could not load this customer."},
        }), 500

    if record is None:
        return jsonify({
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "No customer with that id."},
        }), 404

    return jsonify({"success": True, "scope": "demo", "notice": DEMO_NOTICE,
                    "customer": record}), 200
