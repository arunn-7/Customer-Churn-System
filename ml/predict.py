"""Inference helpers for the trained churn model.

The persisted ``GradientBoostingClassifier`` in ``ml/model.pkl`` was fitted on a
DataFrame whose columns were produced by :func:`ml.preprocess.preprocess_data`.
scikit-learn records the exact feature names *and their order* in
``model.feature_names_in_``, and ``predict``/``predict_proba`` raise

    ValueError: The feature names should match those that were passed during fit.
    Feature names must be in the same order as they were in fit.

if the frame handed to them differs in name or order. Building the frame
straight from request JSON (``pd.DataFrame([data])``) therefore made the endpoint
fail whenever the client did not happen to send keys in the training order --
Flask's JSON provider sorts keys by default, so that was most requests.

This module now validates the payload and rebuilds the frame column-by-column in
the model's own order, so equivalent inputs score identically regardless of the
order their keys arrive in.
"""

from __future__ import annotations

import math
import os
from typing import Any, Mapping

import joblib
import pandas as pd

# Resolved relative to this file so the model loads from any working directory.
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.pkl")

# Load trained model
model = joblib.load(MODEL_PATH)

# Training column names, in training order. This is the single source of truth
# for the prediction contract; nothing here may reorder or rename them.
FEATURE_NAMES: list[str] = [str(name) for name in model.feature_names_in_]
FEATURE_SET = frozenset(FEATURE_NAMES)

# The four raw numeric measures carried by the customer record.
NUMERIC_FEATURES: tuple[str, ...] = (
    "SeniorCitizen",
    "tenure",
    "MonthlyCharges",
    "TotalCharges",
)

# Everything else is a drop_first dummy column, so an absent flag correctly means
# "not this category" and safely defaults to False.
FLAG_FEATURES: tuple[str, ...] = tuple(
    name for name in FEATURE_NAMES if name not in NUMERIC_FEATURES
)


class FeatureValidationError(ValueError):
    """Raised when a payload cannot be mapped onto the model's feature vector.

    Carries every problem found so the HTTP layer can report them all at once
    instead of failing on the first bad field.
    """

    def __init__(self, issues: list[dict[str, str]]) -> None:
        self.issues = issues
        summary = "; ".join(f"{i['field']}: {i['issue']}" for i in issues if i.get("field"))
        super().__init__(summary or "invalid feature payload")


def _coerce_numeric(raw: Any) -> float:
    """Return ``raw`` as a finite, non-negative float or raise ValueError."""
    if isinstance(raw, bool):
        raise ValueError("expected a number, got a boolean")
    if not isinstance(raw, (int, float)):
        raise ValueError("expected a number")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("expected a finite number")
    if value < 0:
        raise ValueError("expected a value greater than or equal to 0")
    return value


def _coerce_flag(raw: Any) -> bool:
    """Return ``raw`` as a bool or raise ValueError."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int) and raw in (0, 1):
        return bool(raw)
    raise ValueError("expected true/false or 0/1")


def build_feature_frame(data: Mapping[str, Any]) -> pd.DataFrame:
    """Validate ``data`` and return a one-row frame aligned to the model.

    Raises :class:`FeatureValidationError` if the payload cannot describe a
    customer at all; unknown extra keys are simply dropped, because the frame is
    rebuilt from :data:`FEATURE_NAMES` rather than from the payload.
    """
    if not isinstance(data, Mapping):
        raise FeatureValidationError(
            [{"field": None, "issue": "expected a JSON object of customer fields"}]
        )
    if not data:
        raise FeatureValidationError(
            [
                {
                    "field": None,
                    "issue": (
                        "request body is empty; at least "
                        f"{', '.join(NUMERIC_FEATURES)} are required"
                    ),
                }
            ]
        )

    values: dict[str, Any] = {}
    issues: list[dict[str, str]] = []

    for name in NUMERIC_FEATURES:
        raw = data.get(name)
        if raw is None:
            issues.append({"field": name, "issue": "field is required"})
            values[name] = 0.0
            continue

        try:
            value = _coerce_numeric(raw)
        except ValueError as exc:
            issues.append({"field": name, "issue": str(exc)})
            values[name] = 0.0
            continue

        if name == "SeniorCitizen" and value not in (0.0, 1.0):
            issues.append({"field": name, "issue": "expected 0 or 1"})
        elif name == "tenure" and not value.is_integer():
            issues.append({"field": name, "issue": "expected a whole number of months"})

        values[name] = value

    for name in FLAG_FEATURES:
        raw = data.get(name, False)
        if raw is None:
            raw = False
        try:
            values[name] = _coerce_flag(raw)
        except ValueError as exc:
            issues.append({"field": name, "issue": str(exc)})
            values[name] = False

    if issues:
        raise FeatureValidationError(issues)

    # Selecting by `columns` guarantees the training names *and* their order,
    # and discards anything unexpected the caller sent.
    return pd.DataFrame([values], columns=FEATURE_NAMES).astype(float)


def predict_customer(data: Mapping[str, Any]) -> dict[str, Any]:
    """Score one customer record and return the churn label and percentage."""
    df = build_feature_frame(data)

    # Prediction
    prediction = model.predict(df)[0]

    # Probability
    probability = model.predict_proba(df)[0][1]

    if prediction:
        result = "Yes"
    else:
        result = "No"

    return {
        "Prediction": result,
        "Probability": float(round(probability * 100, 2))
    }


# Test
if __name__ == "__main__":

    sample = {
        "SeniorCitizen": 0,
        "tenure": 12,
        "MonthlyCharges": 75.25,
        "TotalCharges": 900.50,

        "gender_Male": True,
        "Partner_Yes": False,
        "Dependents_Yes": False,
        "PhoneService_Yes": True,
        "MultipleLines_No phone service": False,
        "MultipleLines_Yes": True,
        "InternetService_Fiber optic": True,
        "InternetService_No": False,
        "OnlineSecurity_No internet service": False,
        "OnlineSecurity_Yes": False,
        "OnlineBackup_No internet service": False,
        "OnlineBackup_Yes": True,
        "DeviceProtection_No internet service": False,
        "DeviceProtection_Yes": False,
        "TechSupport_No internet service": False,
        "TechSupport_Yes": False,
        "StreamingTV_No internet service": False,
        "StreamingTV_Yes": True,
        "StreamingMovies_No internet service": False,
        "StreamingMovies_Yes": True,
        "Contract_One year": False,
        "Contract_Two year": False,
        "PaperlessBilling_Yes": True,
        "PaymentMethod_Credit card (automatic)": False,
        "PaymentMethod_Electronic check": True,
        "PaymentMethod_Mailed check": False
    }

    print(predict_customer(sample))
