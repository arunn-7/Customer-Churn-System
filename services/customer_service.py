"""Read-only queries over the `customers` table.

All dashboard, customer-list and chart data comes from here so the SQL lives in
one place. Read-only by design: nothing in this module inserts, updates or
deletes, which keeps the existing 7,032 records untouched.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, or_, select

from database.db import db
from models.customer import Customer

# Columns exposed to the browser, in display order.
LIST_COLUMNS = [
    "customer_id",
    "gender",
    "senior_citizen",
    "partner",
    "dependents",
    "tenure",
    "contract",
    "internet_service",
    "payment_method",
    "monthly_charges",
    "total_charges",
    "churn",
]

SORTABLE = {
    "customer_id": Customer.customer_id,
    "tenure": Customer.tenure,
    "monthly_charges": Customer.monthly_charges,
    "total_charges": Customer.total_charges,
    "contract": Customer.contract,
    "internet_service": Customer.internet_service,
    "churn": Customer.churn,
}

# Demo/scope filter: the IBM sample dataset is exactly the rows with no owning
# company. Demo endpoints must never surface company-owned records.
SAMPLE_SCOPE = Customer.company_id.is_(None)

PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _churn_counts() -> tuple[int, int]:
    """(churned, retained) via a single grouped query."""
    rows = db.session.execute(
        select(Customer.churn, func.count(Customer.id)).where(SAMPLE_SCOPE).group_by(Customer.churn)
    ).all()
    counts = {label: count for label, count in rows}
    return int(counts.get("Yes", 0)), int(counts.get("No", 0))


def stats() -> dict[str, Any]:
    """Headline KPI figures for the dashboard."""
    churned, retained = _churn_counts()
    total = churned + retained

    avg = db.session.execute(
        select(
            func.avg(Customer.tenure),
            func.avg(Customer.monthly_charges),
            func.avg(Customer.total_charges),
        ).where(SAMPLE_SCOPE)
    ).one()

    return {
        "total_customers": total,
        "churned": churned,
        "retained": retained,
        "churn_rate": round(churned / total * 100.0, 2) if total else 0.0,
        "retention_rate": round(retained / total * 100.0, 2) if total else 0.0,
        "avg_tenure": round(float(avg[0] or 0), 1),
        "avg_monthly_charges": round(float(avg[1] or 0), 2),
        "avg_total_charges": round(float(avg[2] or 0), 2),
        "revenue_at_risk": round(
            float(
                db.session.execute(
                    select(func.coalesce(func.sum(Customer.monthly_charges), 0)).where(
                        SAMPLE_SCOPE, Customer.churn == "Yes"
                    )
                ).scalar()
            ),
            2,
        ),
    }


def _grouped(column, churned_only: bool = False) -> list[dict[str, Any]]:
    """Category, customer count and churn count for one column, largest first."""
    # The churn tally always tests customers.churn, never the grouping column.
    churn_sum = func.sum(case((Customer.churn == "Yes", 1), else_=0))
    stmt = select(
        column.label("label"),
        func.count(Customer.id).label("count"),
        churn_sum.label("churned"),
    ).where(SAMPLE_SCOPE).group_by(column)
    if churned_only:
        stmt = stmt.where(column == "Yes")
    stmt = stmt.order_by(func.count(Customer.id).desc())

    rows = []
    for label, count, churned in db.session.execute(stmt).all():
        count = int(count)
        churned = int(churned or 0)
        rows.append(
            {
                "label": label,
                "count": count,
                "churned": churned,
                "churn_rate": round(churned / count * 100.0, 2) if count else 0.0,
            }
        )
    return rows


def analytics() -> dict[str, Any]:
    """Aggregations backing every chart on the dashboard."""
    return {
        "by_contract": _grouped(Customer.contract),
        "by_internet_service": _grouped(Customer.internet_service),
        "by_payment_method": _grouped(Customer.payment_method),
        "by_tech_support": _grouped(Customer.tech_support),
        "by_tenure_band": _tenure_bands(),
        "by_charges_band": _charges_bands(),
        "churned_by_contract": _grouped(Customer.contract, churned_only=True),
    }


def _tenure_bands() -> list[dict[str, Any]]:
    """Tenure is bucketed in SQL, so aggregate in Python instead of via _grouped."""
    rows = db.session.execute(
        select(Customer.tenure, Customer.churn).where(
            SAMPLE_SCOPE, Customer.churn.isnot(None)
        )
    ).all()
    bands = [("0-12 months", 0, 12), ("13-24 months", 13, 24),
             ("25-48 months", 25, 48), ("49+ months", 49, 10_000)]
    out = []
    for label, low, high in bands:
        total = 0
        churned = 0
        for tenure, churn in rows:
            if low <= (tenure or 0) <= high:
                total += 1
                if churn == "Yes":
                    churned += 1
        out.append(
            {
                "label": label,
                "count": total,
                "churned": churned,
                "churn_rate": round(churned / total * 100.0, 2) if total else 0.0,
            }
        )
    return out


def _charges_bands() -> list[dict[str, Any]]:
    """Monthly-charge bands, aggregated in Python to keep the SQL simple."""
    rows = db.session.execute(
        select(Customer.monthly_charges, Customer.churn).where(
            SAMPLE_SCOPE, Customer.churn.isnot(None)
        )
    ).all()
    bands = [("Under $35", 0, 34.999), ("$35 - $70", 35, 70), ("Over $70", 70.001, 10_000)]
    out = []
    for label, low, high in bands:
        total = 0
        churned = 0
        for charges, churn in rows:
            if low <= (charges or 0) <= high:
                total += 1
                if churn == "Yes":
                    churned += 1
        out.append(
            {
                "label": label,
                "count": total,
                "churned": churned,
                "churn_rate": round(churned / total * 100.0, 2) if total else 0.0,
            }
        )
    return out


def list_customers(
    search: str = "",
    page: int = 1,
    per_page: int = PAGE_SIZE,
    sort: str = "customer_id",
    order: str = "asc",
    churn: str = "",
) -> dict[str, Any]:
    """Paginated, searchable customer list.

    ``search`` matches customer id, gender, contract, internet service or payment
    method. Filters and ordering are whitelisted, never interpolated raw.
    """
    page = max(1, int(page or 1))
    per_page = max(1, min(MAX_PAGE_SIZE, int(per_page or PAGE_SIZE)))
    sort_column = SORTABLE.get(sort, Customer.customer_id)
    sort_column = sort_column.desc() if str(order).lower() == "desc" else sort_column.asc()

    conditions = [SAMPLE_SCOPE]
    if search:
        term = f"%{search.strip()}%"
        conditions.append(
            or_(
                Customer.customer_id.like(term),
                Customer.gender.like(term),
                Customer.contract.like(term),
                Customer.internet_service.like(term),
                Customer.payment_method.like(term),
            )
        )
    if churn in ("Yes", "No"):
        conditions.append(Customer.churn == churn)

    total = db.session.execute(
        select(func.count(Customer.id)).where(*conditions)
    ).scalar() or 0

    rows = db.session.execute(
        select(Customer)
        .where(*conditions)
        .order_by(sort_column)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).scalars().all()

    return {
        "customers": [
            {column: getattr(row, column) for column in LIST_COLUMNS} for row in rows
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": int(total),
            "pages": max(1, -(-int(total) // per_page)),
            "has_next": page * per_page < int(total),
            "has_prev": page > 1,
        },
        "filters": {"search": search, "sort": sort, "order": order, "churn": churn},
    }


def find_customer(customer_id: str) -> dict[str, Any] | None:
    """One customer by their public id, or None. DEMO SCOPE (any company)."""
    row = db.session.execute(
        select(Customer).where(
            Customer.customer_id == customer_id, SAMPLE_SCOPE
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {column: getattr(row, column) for column in LIST_COLUMNS}


# ======================================================================
# COMPANY SCOPE
#
# Every function below takes the owning company_id and filters on it. The
# caller must pass the id derived from the authenticated session, never a
# request parameter. `company_id IS NULL` (IBM sample data) can therefore
# never match, and company-owned rows can never leak into the demo scope.
# ======================================================================


def _company_filter(company_id: int | None):
    """SQL predicate restricting rows to one company.

    A falsy company_id yields a predicate that matches nothing, so a caller
    that somehow lost its tenant context gets an empty result rather than
    every company's rows.
    """
    if company_id is None:
        return Customer.company_id.is_(None) & (Customer.id < 0)
    return Customer.company_id == company_id


def company_stats(company_id: int | None) -> dict[str, Any]:
    """Headline KPIs for one company. IBM sample rows are excluded."""
    if company_id is None:
        return {
            "total_customers": 0, "churned": 0, "retained": 0,
            "churn_rate": 0.0, "retention_rate": 0.0,
            "avg_tenure": 0, "avg_monthly_charges": 0, "avg_total_charges": 0,
            "revenue_at_risk": 0,
        }

    rows = db.session.execute(
        select(Customer.churn, func.count(Customer.id))
        .where(_company_filter(company_id))
        .group_by(Customer.churn)
    ).all()
    counts = {label: int(count) for label, count in rows}
    churned = counts.get("Yes", 0)
    retained = counts.get("No", 0)
    total = churned + retained

    avg = db.session.execute(
        select(
            func.avg(Customer.tenure),
            func.avg(Customer.monthly_charges),
            func.avg(Customer.total_charges),
            func.coalesce(func.sum(Customer.monthly_charges), 0),
        ).where(_company_filter(company_id), Customer.churn == "Yes")
    ).one()

    return {
        "total_customers": total,
        "churned": churned,
        "retained": retained,
        # No predictions yet -> no meaningful rate, so report None not 0.0.
        "churn_rate": round(churned / total * 100.0, 2) if total else None,
        "retention_rate": round(retained / total * 100.0, 2) if total else None,
        "avg_tenure": round(float(avg[0] or 0), 1),
        "avg_monthly_charges": round(float(avg[1] or 0), 2),
        "avg_total_charges": round(float(avg[2] or 0), 2),
        "revenue_at_risk": round(float(avg[3] or 0), 2),
    }


def company_customers(
    company_id: int | None,
    *,
    search: str = "",
    page: int = 1,
    per_page: int = PAGE_SIZE,
    sort: str = "customer_id",
    order: str = "asc",
    churn: str = "",
) -> dict[str, Any]:
    """Paginated customer list scoped to one company."""
    page = max(1, int(page or 1))
    per_page = max(1, min(MAX_PAGE_SIZE, int(per_page or PAGE_SIZE)))
    sort_column = SORTABLE.get(sort, Customer.customer_id)
    sort_column = sort_column.desc() if str(order).lower() == "desc" else sort_column.asc()

    conditions = [_company_filter(company_id)]

    if search:
        term = f"%{search.strip()}%"
        conditions.append(
            or_(
                Customer.customer_id.like(term),
                Customer.gender.like(term),
                Customer.contract.like(term),
                Customer.internet_service.like(term),
                Customer.payment_method.like(term),
            )
        )
    if churn in ("Yes", "No"):
        conditions.append(Customer.churn == churn)

    total = db.session.execute(
        select(func.count(Customer.id)).where(*conditions)
    ).scalar() or 0

    rows = db.session.execute(
        select(Customer)
        .where(*conditions)
        .order_by(sort_column)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).scalars().all()

    return {
        "customers": [
            {column: getattr(row, column) for column in LIST_COLUMNS} for row in rows
        ],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": int(total),
            "pages": max(1, -(-int(total) // per_page)),
            "has_next": page * per_page < int(total),
            "has_prev": page > 1,
        },
        "filters": {"search": search, "sort": sort, "order": order, "churn": churn},
    }


def company_customer_detail(company_id: int | None, customer_id: str) -> dict[str, Any] | None:
    """Fetch one customer, verifying it belongs to this company.

    Ownership is enforced in the WHERE clause, so a guessed identifier from
    another company simply returns None rather than leaking the record.
    """
    if company_id is None:
        return None
    row = db.session.execute(
        select(Customer).where(
            Customer.customer_id == customer_id,
            Customer.company_id == company_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {column: getattr(row, column) for column in LIST_COLUMNS}


def company_analytics(company_id: int | None) -> dict[str, Any]:
    """Chart aggregations scoped to one company. Empty when no data."""
    empty = {
        "by_contract": [], "by_internet_service": [], "by_payment_method": [],
        "by_tech_support": [], "by_tenure_band": [], "by_charges_band": [],
    }
    if company_id is None:
        return empty

    def grouped(column) -> list[dict[str, Any]]:
        churn_sum = func.sum(case((Customer.churn == "Yes", 1), else_=0))
        stmt = (
            select(column.label("label"), func.count(Customer.id).label("count"),
                   churn_sum.label("churned"))
            .where(_company_filter(company_id))
            .group_by(column)
            .order_by(func.count(Customer.id).desc())
        )
        out = []
        for label, count, churned in db.session.execute(stmt).all():
            count = int(count)
            churned = int(churned or 0)
            out.append({
                "label": label, "count": count, "churned": churned,
                "churn_rate": round(churned / count * 100.0, 2) if count else 0.0,
            })
        return out

    rows = db.session.execute(
        select(Customer.tenure, Customer.monthly_charges, Customer.churn)
        .where(_company_filter(company_id))
    ).all()

    bands = [("0-12 months", lambda t: t <= 12), ("13-24 months", lambda t: 13 <= t <= 24),
             ("25-48 months", lambda t: 25 <= t <= 48), ("49+ months", lambda t: t > 48)]
    tenure_bands = []
    for label, test in bands:
        total = sum(1 for tenure, _c, _h in rows if test(tenure or 0))
        churned = sum(1 for tenure, _c, h in rows if test(tenure or 0) and h == "Yes")
        tenure_bands.append({
            "label": label, "count": total, "churned": churned,
            "churn_rate": round(churned / total * 100.0, 2) if total else 0.0,
        })

    charge_bands = [("Under $35", lambda m: m < 35), ("$35 - $70", lambda m: 35 <= m <= 70),
                    ("Over $70", lambda m: m > 70)]
    charges = []
    for label, test in charge_bands:
        total = sum(1 for _t, m, _h in rows if test(m or 0))
        churned = sum(1 for _t, m, h in rows if test(m or 0) and h == "Yes")
        charges.append({
            "label": label, "count": total, "churned": churned,
            "churn_rate": round(churned / total * 100.0, 2) if total else 0.0,
        })

    return {
        "by_contract": grouped(Customer.contract),
        "by_internet_service": grouped(Customer.internet_service),
        "by_payment_method": grouped(Customer.payment_method),
        "by_tech_support": grouped(Customer.tech_support),
        "by_tenure_band": tenure_bands,
        "by_charges_band": charges,
    }
