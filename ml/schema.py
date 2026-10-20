"""User-facing form schema and the friendly-field -> model-feature mapping.

The form collects ordinary customer attributes ("Contract", "Internet Service",
"Payment Method"). The trained model, however, was fitted on the output of
``pd.get_dummies(df, drop_first=True)``, so it expects 30 one-hot columns with
technical names such as ``PaymentMethod_Electronic check``.

This module bridges the two. The dummy column layout is *derived from the
persisted model* at import time rather than hand-written, and the result is
asserted against ``model.feature_names_in_``. If the model is ever retrained on
different data, the assertions fail loudly at start-up instead of silently
producing wrong predictions.

Deriving the layout by replaying ``get_dummies`` over the schema's own option
lists reproduces training exactly, because training sorted each column's
categories alphabetically and dropped the first one.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from ml.predict import (
    FEATURE_NAMES,
    FEATURE_SET,
    FLAG_FEATURES,
    NUMERIC_FEATURES,
    FeatureValidationError,
)

# ---------------------------------------------------------------------------
# Form definition
#
# `key`      -> field name in the friendly payload (matches the CSV column name)
# `options`  -> the exact category strings seen during training. Order here is
#               cosmetic; get_dummies sorts them itself.
# `dummies`  -> filled in by _derive_dummy_map(), never written by hand.
# ---------------------------------------------------------------------------

FIELDS: list[dict[str, Any]] = [
    {
        "key": "SeniorCitizen",
        "label": "Senior Citizen",
        "type": "select",
        "group": "account",
        "required": True,
        "help": "Whether the customer is 65 or older.",
        "options": [
            {"value": 0, "label": "No"},
            {"value": 1, "label": "Yes"},
        ],
    },
    {
        "key": "tenure",
        "label": "Tenure (months)",
        "type": "number",
        "group": "account",
        "required": True,
        "min": 0,
        "max": 72,
        "step": 1,
        "help": "How long the customer has been with the company (1-72 in this dataset).",
    },
    {
        "key": "gender",
        "label": "Gender",
        "type": "select",
        "group": "account",
        "required": True,
        "options": [{"value": "Female", "label": "Female"},
                    {"value": "Male", "label": "Male"}],
    },
    {
        "key": "Partner",
        "label": "Has Partner",
        "type": "select",
        "group": "account",
        "required": True,
        "options": [{"value": "No", "label": "No"}, {"value": "Yes", "label": "Yes"}],
    },
    {
        "key": "Dependents",
        "label": "Has Dependents",
        "type": "select",
        "group": "account",
        "required": True,
        "options": [{"value": "No", "label": "No"}, {"value": "Yes", "label": "Yes"}],
    },
    {
        "key": "Contract",
        "label": "Contract Type",
        "type": "select",
        "group": "billing",
        "required": True,
        "help": "Longer contracts are strongly associated with lower churn.",
        "options": [
            {"value": "Month-to-month", "label": "Month to month"},
            {"value": "One year", "label": "One year"},
            {"value": "Two year", "label": "Two year"},
        ],
    },
    {
        "key": "PaymentMethod",
        "label": "Payment Method",
        "type": "select",
        "group": "billing",
        "required": True,
        "help": "Electronic check has the highest observed churn rate.",
        "options": [
            {"value": "Bank transfer (automatic)", "label": "Bank transfer (automatic)"},
            {"value": "Credit card (automatic)", "label": "Credit card (automatic)"},
            {"value": "Electronic check", "label": "Electronic check"},
            {"value": "Mailed check", "label": "Mailed check"},
        ],
    },
    {
        "key": "PaperlessBilling",
        "label": "Paperless Billing",
        "type": "select",
        "group": "billing",
        "required": True,
        "options": [{"value": "No", "label": "No"}, {"value": "Yes", "label": "Yes"}],
    },
    {
        "key": "MonthlyCharges",
        "label": "Monthly Charges",
        "type": "number",
        "group": "billing",
        "required": True,
        "min": 0,
        "max": 200,
        "step": 0.01,
        "help": "Current monthly bill in USD (18.25-118.75 in this dataset).",
    },
    {
        "key": "TotalCharges",
        "label": "Total Charges",
        "type": "number",
        "group": "billing",
        "required": True,
        "min": 0,
        "max": 10000,
        "step": 0.01,
        "help": "Total amount billed over the customer's lifetime.",
    },
    {
        "key": "PhoneService",
        "label": "Phone Service",
        "type": "select",
        "group": "services",
        "required": True,
        "options": [{"value": "No", "label": "No"}, {"value": "Yes", "label": "Yes"}],
    },
    {
        "key": "MultipleLines",
        "label": "Multiple Lines",
        "type": "select",
        "group": "services",
        "required": True,
        "options": [
            {"value": "No", "label": "No"},
            {"value": "No phone service", "label": "No phone service"},
            {"value": "Yes", "label": "Yes"},
        ],
    },
    {
        "key": "InternetService",
        "label": "Internet Service",
        "type": "select",
        "group": "services",
        "required": True,
        "help": "Fiber optic is the strongest churn driver in this dataset.",
        "options": [
            {"value": "DSL", "label": "DSL"},
            {"value": "Fiber optic", "label": "Fiber optic"},
            {"value": "No", "label": "No internet service"},
        ],
    },
    {
        "key": "OnlineSecurity",
        "label": "Online Security",
        "type": "select",
        "group": "addons",
        "required": True,
        "options": [
            {"value": "No", "label": "No"},
            {"value": "Yes", "label": "Yes"},
            {"value": "No internet service", "label": "No internet service"},
        ],
    },
    {
        "key": "OnlineBackup",
        "label": "Online Backup",
        "type": "select",
        "group": "addons",
        "required": True,
        "options": [
            {"value": "No", "label": "No"},
            {"value": "Yes", "label": "Yes"},
            {"value": "No internet service", "label": "No internet service"},
        ],
    },
    {
        "key": "DeviceProtection",
        "label": "Device Protection",
        "type": "select",
        "group": "addons",
        "required": True,
        "options": [
            {"value": "No", "label": "No"},
            {"value": "Yes", "label": "Yes"},
            {"value": "No internet service", "label": "No internet service"},
        ],
    },
    {
        "key": "TechSupport",
        "label": "Technical Support",
        "type": "select",
        "group": "addons",
        "required": True,
        "options": [
            {"value": "No", "label": "No"},
            {"value": "Yes", "label": "Yes"},
            {"value": "No internet service", "label": "No internet service"},
        ],
    },
    {
        "key": "StreamingTV",
        "label": "Streaming TV",
        "type": "select",
        "group": "addons",
        "required": True,
        "options": [
            {"value": "No", "label": "No"},
            {"value": "Yes", "label": "Yes"},
            {"value": "No internet service", "label": "No internet service"},
        ],
    },
    {
        "key": "StreamingMovies",
        "label": "Streaming Movies",
        "type": "select",
        "group": "addons",
        "required": True,
        "options": [
            {"value": "No", "label": "No"},
            {"value": "Yes", "label": "Yes"},
            {"value": "No internet service", "label": "No internet service"},
        ],
    },
]

GROUPS: list[dict[str, str]] = [
    {"key": "account", "title": "Account & Demographics"},
    {"key": "services", "title": "Phone & Internet Services"},
    {"key": "addons", "title": "Service Add-ons"},
    {"key": "billing", "title": "Contract & Billing"},
]

FIELDS_BY_KEY: dict[str, dict[str, Any]] = {f["key"]: f for f in FIELDS}


def _derive_dummy_map() -> dict[str, dict[str, Any]]:
    """Replay get_dummies over the schema's options to recover dummy columns.

    Training applied ``pd.get_dummies(df, drop_first=True)``, which sorts each
    column's categories and drops the first. Each field is therefore probed on
    its own single-column frame: probing several fields at once would introduce
    filler categories that displace the value drop_first removes, and the
    recovered baseline would silently be wrong.
    """
    categorical = [f for f in FIELDS if f["type"] == "select" and f["key"] != "SeniorCitizen"]

    mapping: dict[str, dict[str, Any]] = {}
    for field in categorical:
        key = field["key"]
        values = [o["value"] for o in field["options"]]

        probe = pd.get_dummies(pd.DataFrame({key: values}), drop_first=True)

        mapping[key] = {
            "dummies": [c for c in probe.columns if c.startswith(f"{key}_")],
            "baseline": sorted(str(v) for v in values)[0],
        }
    return mapping


_DUMMY_MAP = _derive_dummy_map()


def _validate_contract() -> None:
    """Fail loudly at import time if schema and model disagree."""
    produced: set[str] = set(NUMERIC_FEATURES)

    for key, entry in _DUMMY_MAP.items():
        dummies = entry["dummies"]
        if not dummies:
            raise RuntimeError(f"schema field {key!r} produced no dummy columns")
        overlap = produced & set(dummies)
        if overlap:
            raise RuntimeError(f"dummy columns claimed twice: {sorted(overlap)}")
        produced.update(dummies)

    if produced != FEATURE_SET:
        missing = sorted(FEATURE_SET - produced)
        extra = sorted(produced - FEATURE_SET)
        raise RuntimeError(
            "schema does not match the trained model. "
            f"missing={missing} unexpected={extra}"
        )

    if sorted(FIELDS_BY_KEY) != sorted(tuple(NUMERIC_FEATURES) + tuple(_DUMMY_MAP)):
        raise RuntimeError("schema fields do not line up with the model's inputs")


_validate_contract()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _issue(field: str, message: str) -> dict[str, str]:
    return {"field": field, "issue": message}


def to_model_features(customer: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a friendly customer payload into the model's 30 features.

    Raises :class:`FeatureValidationError` with messages phrased in the user's
    own field names, not dummy-column names.
    """
    if not isinstance(customer, Mapping):
        raise FeatureValidationError([_issue("body", "expected a JSON object of customer fields")])
    if not customer:
        raise FeatureValidationError([_issue("body", "request body is empty")])

    issues: list[dict[str, str]] = []
    values: dict[str, Any] = {}

    for field in FIELDS:
        key = field["key"]
        label = field["label"]
        raw = customer.get(key)

        if raw is None or raw == "":
            if field["required"]:
                issues.append(_issue(label, "This field is required"))
            continue

        if field["type"] == "number":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                issues.append(_issue(label, "Enter a number"))
                continue
            number = float(raw)
            low, high = field.get("min"), field.get("max")
            if low is not None and number < low:
                issues.append(_issue(label, f"Must be at least {low:g}"))
                continue
            if high is not None and number > high:
                issues.append(_issue(label, f"Must be at most {high:g}"))
                continue
            if field["key"] == "tenure" and not number.is_integer():
                issues.append(_issue(label, "Enter a whole number of months"))
                continue
            values[key] = number
            continue

        # select
        allowed = {o["value"] for o in field["options"]}
        # JSON gives us 0/1 for SeniorCitizen and strings for the rest.
        match = None
        for option in field["options"]:
            if raw == option["value"] or str(raw) == str(option["value"]):
                match = option
                break
        if match is None:
            issues.append(
                _issue(label, "Choose one of: " + ", ".join(str(o["value"]) for o in field["options"]))
            )
            continue
        values[key] = match["value"]

    if issues:
        raise FeatureValidationError(issues)

    # Unset dummy flags default to False: under drop_first encoding that is the
    # reference category, which is a meaningful state rather than missing data.
    for name in FLAG_FEATURES:
        values[name] = False

    # Light up the dummy column for each categorical choice.
    for key, entry in _DUMMY_MAP.items():
        chosen = values.get(key, entry["baseline"])
        active = f"{key}_{chosen}" if chosen != entry["baseline"] else None
        for dummy in entry["dummies"]:
            values[dummy] = dummy == active

    return values


def schema_payload() -> dict[str, Any]:
    """Serialisable form definition for GET /predict/schema."""
    fields = []
    for field in FIELDS:
        entry = {
            "key": field["key"],
            "label": field["label"],
            "type": field["type"],
            "group": field["group"],
            "required": field.get("required", False),
            "help": field.get("help", ""),
        }
        for bound in ("min", "max", "step"):
            if field.get(bound) is not None:
                entry[bound] = field[bound]
        if field["type"] == "select":
            entry["options"] = [
                {"value": o["value"], "label": o["label"]} for o in field["options"]
            ]
        fields.append(entry)

    return {
        "groups": GROUPS,
        "fields": fields,
        "baseline_note": (
            "Category options are the exact values seen during model training."
        ),
        "feature_count": len(FEATURE_NAMES),
    }


def field_label(key: str) -> str:
    field = FIELDS_BY_KEY.get(key)
    return field["label"] if field else key


def categorical_field_of(dummy: str) -> str | None:
    """Return the friendly field key that owns a given dummy column."""
    for key, entry in _DUMMY_MAP.items():
        if dummy in entry["dummies"]:
            return key
    return None
