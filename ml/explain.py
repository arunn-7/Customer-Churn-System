"""Per-customer explanation of a churn prediction.

Answers "why was this customer flagged?" by measuring the actual model, not a
hand-written story. For each user-facing field the customer's value is swapped
for its baseline and the model is re-scored; the resulting change in churn
probability is that field's contribution to this prediction.

This is a one-at-a-time sensitivity analysis. It is cheap (one extra
``predict_proba`` call per field on a single-row frame), needs no extra
dependency, and because it re-runs the real model it cannot drift away from what
the model actually predicts.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from ml.predict import FEATURE_NAMES, model
from ml.schema import FIELDS, FIELDS_BY_KEY, _DUMMY_MAP, to_model_features


def _probability(features: Mapping[str, Any]) -> float:
    frame = pd.DataFrame([features], columns=FEATURE_NAMES).astype(float)
    return float(model.predict_proba(frame)[0][1])


def _baseline_value(field: Mapping[str, Any]) -> Any:
    """The reference value each field is compared against."""
    key = field["key"]
    if key == "SeniorCitizen":
        return 0
    if key in _DUMMY_MAP:
        return _DUMMY_MAP[key]["baseline"]
    return 0  # tenure, MonthlyCharges, TotalCharges: a brand-new customer


def _display(field: Mapping[str, Any], value: Any) -> str:
    if value is None:
        return "-"
    if field["type"] == "select":
        for option in field["options"]:
            if option["value"] == value:
                return option["label"]
        return str(value)
    if field["key"] == "tenure":
        return f"{value:g} months"
    if field["key"] == "SeniorCitizen":
        return "Yes" if int(value) == 1 else "No"
    return f"{float(value):,.2f}"


def risk_band(probability: float) -> dict[str, str]:
    """Classify a churn probability into an actionable band."""
    if probability >= 0.65:
        return {"level": "high", "label": "High risk", "action": "Contact within 24 hours"}
    if probability >= 0.40:
        return {"level": "medium", "label": "Medium risk", "action": "Review within 7 days"}
    return {"level": "low", "label": "Low risk", "action": "No action required"}


def explain_prediction(
    customer: Mapping[str, Any],
    features: Mapping[str, Any],
    top: int = 6,
) -> list[dict[str, Any]]:
    """Rank fields by how much they move this customer's churn probability.

    ``impact`` is expressed in percentage points. Positive means the customer's
    chosen value raises churn risk relative to the field's baseline.
    """
    baseline_probability = _probability(features)

    factors: list[dict[str, Any]] = []
    for field in FIELDS:
        key = field["key"]
        current = customer.get(key)
        if current is None:
            continue

        probe = dict(customer)
        probe[key] = _baseline_value(field)
        try:
            counterfactual = to_model_features(probe)
        except Exception:
            continue

        impact = (baseline_probability - _probability(counterfactual)) * 100.0

        factors.append(
            {
                "field": key,
                "label": field["label"],
                "value": _display(field, current),
                "baseline": _display(field, _baseline_value(field)),
                "impact": round(impact, 2),
                "direction": "increases" if impact > 0 else "reduces",
            }
        )

    # Strongest churn drivers first; ties broken by field order for stability.
    order = {field["key"]: i for i, field in enumerate(FIELDS)}
    factors.sort(key=lambda f: (-abs(f["impact"]), order[f["field"]]))
    return factors[:top]


def prediction_details(customer: Mapping[str, Any], top: int = 6) -> dict[str, Any]:
    """Prediction plus band and top drivers, for one friendly customer record."""
    features = to_model_features(customer)

    probability = _probability(features)
    label = "Yes" if model.predict(
        pd.DataFrame([features], columns=FEATURE_NAMES).astype(float)
    )[0] else "No"

    return {
        "prediction": {
            "churn": label,
            "churn_probability": float(round(probability * 100.0, 2)),
        },
        "risk": risk_band(probability),
        "factors": explain_prediction(customer, features, top=top),
    }
