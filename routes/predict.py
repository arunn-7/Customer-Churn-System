"""HTTP layer for churn predictions.

Owns request parsing, input validation and response shaping. Scoring itself
lives in :mod:`ml.predict`; this module deliberately never lets a traceback or
an internal message reach the client.

All endpoints require authentication. The model itself is stateless, so these
routes are not restricted to demo-viewing roles: any signed-in user of any role
may score a customer. Results are per-request and are never persisted as a
company's operational records here.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from ml.explain import prediction_details
from ml.predict import (
    FEATURE_SET,
    NUMERIC_FEATURES,
    FeatureValidationError,
    predict_customer,
)
from ml.schema import FIELDS_BY_KEY, schema_payload, to_model_features
from security.decorators import login_required

logger = logging.getLogger(__name__)

predict_bp = Blueprint("predict", __name__)

# Keys documented in the module docstring, surfaced to callers as guidance.
_REQUIRED_HINT = ", ".join(NUMERIC_FEATURES)

# Friendly names that cannot collide with a raw one-hot feature name.
_CATEGORICAL_FIELD_KEYS = set(FIELDS_BY_KEY) - set(NUMERIC_FEATURES)


def _failure(
    status: int,
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
):
    """Return the canonical failure envelope."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return jsonify({"success": False, "error": error}), status


@predict_bp.route("/predict", methods=["POST"])
@login_required
def predict():
    # silent=True so malformed JSON and a wrong/absent Content-Type come back as
    # None instead of raising a 415 or an HTML error page.
    data = request.get_json(silent=True)

    if data is None:
        return _failure(
            400,
            "INVALID_JSON",
            "Request body must be valid JSON sent with Content-Type: application/json.",
        )

    if not isinstance(data, dict):
        return _failure(
            400,
            "INVALID_JSON",
            "Request body must be a JSON object of customer fields.",
        )

    # Two accepted payload shapes:
    #   * friendly field names ("Contract": "One year") -- what the form sends.
    #     These are mapped to the model's 30 one-hot features here, so the
    #     browser never has to know about dummy-column names.
    #   * the original 30 one-hot feature names -- unchanged for existing clients.
    #
    # Discriminate on the *categorical* friendly names only. The four numeric
    # names (tenure, MonthlyCharges, ...) are spelled identically in both shapes,
    # so they cannot be used to tell them apart; the categorical names such as
    # "Contract" or "gender" never appear in a raw one-hot payload.
    friendly = bool(set(data) & _CATEGORICAL_FIELD_KEYS)

    if friendly:
        try:
            features = to_model_features(data)
        except FeatureValidationError as exc:
            return _failure(
                400,
                "VALIDATION_ERROR",
                "One or more customer fields are invalid.",
                exc.issues,
            )
        known = set(FIELDS_BY_KEY)
    else:
        features = data
        known = FEATURE_SET

    try:
        result = predict_customer(features)
    except FeatureValidationError as exc:
        # Client's fault and fully described by exc.issues -- safe to return.
        return _failure(
            400,
            "VALIDATION_ERROR",
            f"One or more customer fields are invalid. Required: {_REQUIRED_HINT}.",
            exc.issues,
        )
    except Exception:
        # Log the detail server-side, return an opaque message to the client.
        logger.exception("Unexpected failure while scoring POST /predict")
        return _failure(
            500,
            "PREDICTION_ERROR",
            "The prediction could not be generated. Please retry.",
        )

    unknown = sorted(key for key in data if key not in known)
    warnings = []
    if unknown:
        warnings.append(f"Ignored unrecognised field(s): {', '.join(unknown)}")

    return (
        jsonify(
            {
                "success": True,
                "prediction": {
                    "churn": result["Prediction"],
                    "churn_probability": result["Probability"],
                },
                "warnings": warnings,
            }
        ),
        200,
    )


@predict_bp.route("/predict/schema", methods=["GET"])
@login_required
def predict_schema():
    """Form definition for the prediction UI.

    The field list, labels and option values are derived from the persisted
    model, so the form cannot drift from what the model was trained on.
    """
    return jsonify({"success": True, **schema_payload()}), 200


@predict_bp.route("/predict/explain", methods=["POST"])
@login_required
def predict_explain():
    """Prediction plus risk band and the fields driving it.

    Accepts the same friendly field names as the form and performs the mapping
    to the model's 30 features here, so the browser never has to know about
    one-hot column names.
    """
    data = request.get_json(silent=True)

    if data is None:
        return _failure(
            400,
            "INVALID_JSON",
            "Request body must be valid JSON sent with Content-Type: application/json.",
        )
    if not isinstance(data, dict):
        return _failure(
            400, "INVALID_JSON", "Request body must be a JSON object of customer fields."
        )

    try:
        result = prediction_details(data)
    except FeatureValidationError as exc:
        return _failure(
            400, "VALIDATION_ERROR", "One or more customer fields are invalid.", exc.issues
        )
    except Exception:
        logger.exception("Unexpected failure while explaining POST /predict/explain")
        return _failure(
            500, "PREDICTION_ERROR", "The explanation could not be generated. Please retry."
        )

    return jsonify({"success": True, **result}), 200
