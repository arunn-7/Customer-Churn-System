"""Verification suite for the POST /predict endpoint.

Runs standalone (no pytest required):

    .\\venv\\Scripts\\python.exe tests\\test_predict_api.py

and is also collectable by pytest if it is installed:

    .\\venv\\Scripts\\python.exe -m pytest tests\\test_predict_api.py -v

Covers: training-order payload, alphabetised payload, key-order independence,
missing fields, empty JSON object, malformed JSON, non-JSON content type,
non-object JSON bodies, wrong data types, unexpected fields, and method guards.
"""

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from app import app  # noqa: E402
from ml.predict import FEATURE_NAMES  # noqa: E402

# Exactly the sample from ml/predict.py, i.e. training feature order.
SAMPLE = {
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
    "PaymentMethod_Mailed check": False,
}

RESULTS: list[tuple[bool, str, str]] = []


def check(condition: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(condition), name, detail))


def post(client, body=None, raw=None, content_type=None):
    if raw is not None:
        return client.post("/predict", data=raw, content_type=content_type)
    return client.post("/predict", json=body)


# --------------------------------------------------------------------------
# 1. Valid payload, training order
# --------------------------------------------------------------------------
def test_valid_training_order(client):
    r = post(client, SAMPLE)
    body = r.get_json()
    ok = (
        r.status_code == 200
        and body["success"] is True
        and body["prediction"]["churn"] in ("Yes", "No")
        and isinstance(body["prediction"]["churn_probability"], (int, float))
        and 0.0 <= body["prediction"]["churn_probability"] <= 100.0
    )
    check(
        ok,
        "1. valid payload (training key order)",
        f"HTTP {r.status_code} -> {json.dumps(body)}",
    )
    return body["prediction"]


# --------------------------------------------------------------------------
# 2. Same payload, keys alphabetised (the case that used to 500)
# --------------------------------------------------------------------------
def test_valid_alphabetical_order(client):
    alphabetised = dict(sorted(SAMPLE.items()))
    r = client.post(
        "/predict",
        data=json.dumps(alphabetised),
        content_type="application/json",
    )
    body = r.get_json()
    ok = r.status_code == 200 and body.get("success") is True
    check(ok, "2. same payload, keys alphabetised", f"HTTP {r.status_code} -> {json.dumps(body)}")
    return body.get("prediction")


# --------------------------------------------------------------------------
# 3. Key-order independence
# --------------------------------------------------------------------------
def test_key_order_independence(client, a, b):
    same = a == b
    check(
        same,
        "3. identical prediction regardless of key order",
        f"training-order={a} vs alphabetised={b}",
    )


# --------------------------------------------------------------------------
# 4. Missing optional fields -> filled, still 200
# --------------------------------------------------------------------------
def test_missing_optional_fields(client):
    trimmed = {k: SAMPLE[k] for k in ("SeniorCitizen", "tenure", "MonthlyCharges", "TotalCharges")}
    r = post(client, trimmed)
    body = r.get_json()
    ok = r.status_code == 200 and body.get("success") is True
    check(
        ok,
        "4a. only the 4 required numerics supplied",
        f"HTTP {r.status_code} -> {json.dumps(body)}",
    )

    no_senior = {k: v for k, v in SAMPLE.items() if k != "SeniorCitizen"}
    r2 = post(client, no_senior)
    body2 = r2.get_json()
    check(
        r2.status_code == 400 and body2["error"]["code"] == "VALIDATION_ERROR",
        "4b. required field SeniorCitizen omitted",
        f"HTTP {r2.status_code} -> {json.dumps(body2)}",
    )


# --------------------------------------------------------------------------
# 5. Empty JSON object -> 400, never a prediction
# --------------------------------------------------------------------------
def test_empty_object(client):
    r = post(client, {})
    body = r.get_json()
    ok = (
        r.status_code == 400
        and body["success"] is False
        and "prediction" not in body
    )
    check(ok, "5. empty JSON object", f"HTTP {r.status_code} -> {json.dumps(body)}")


# --------------------------------------------------------------------------
# 6. Malformed JSON / non-JSON request
# --------------------------------------------------------------------------
def test_malformed_and_non_json(client):
    r = client.post("/predict", data="{not json", content_type="application/json")
    body = r.get_json()
    check(
        r.status_code == 400 and body["error"]["code"] == "INVALID_JSON",
        "6a. malformed JSON",
        f"HTTP {r.status_code} -> {json.dumps(body)}",
    )

    r2 = client.post("/predict", data=SAMPLE, content_type="text/plain")
    body2 = r2.get_json()
    check(
        r2.status_code == 400 and body2["error"]["code"] == "INVALID_JSON",
        "6b. non-JSON content type",
        f"HTTP {r2.status_code} -> {json.dumps(body2)}",
    )

    r3 = client.post("/predict")
    check(
        r3.status_code == 400 and r3.get_json()["error"]["code"] == "INVALID_JSON",
        "6c. empty request body",
        f"HTTP {r3.status_code} -> {json.dumps(r3.get_json())}",
    )


# --------------------------------------------------------------------------
# 7. Non-object JSON
# --------------------------------------------------------------------------
def test_non_object_json(client):
    for label, raw in (("array", "[1, 2, 3]"), ("string", '"hello"'), ("number", "42")):
        r = client.post("/predict", data=raw, content_type="application/json")
        body = r.get_json()
        check(
            r.status_code == 400 and body["error"]["code"] == "INVALID_JSON",
            f"7. JSON {label} body",
            f"HTTP {r.status_code} -> {json.dumps(body)}",
        )


# --------------------------------------------------------------------------
# 8. Incorrect data types -> 400 with a field-level reason
# --------------------------------------------------------------------------
def test_bad_types(client):
    cases = {
        "tenure is a string": {"tenure": "twelve"},
        "tenure is negative": {"tenure": -5},
        "tenure is fractional": {"tenure": 12.5},
        "MonthlyCharges is null": {"MonthlyCharges": None},
        "SeniorCitizen out of range": {"SeniorCitizen": 7},
        "SeniorCitizen is boolean": {"SeniorCitizen": True},
        "TotalCharges is a list": {"TotalCharges": [1, 2]},
        "flag is a string": {"TechSupport_Yes": "yes"},
        "flag is a float": {"PaperlessBilling_Yes": 1.0},
    }
    for label, override in cases.items():
        payload = {**SAMPLE, **override}
        r = post(client, payload)
        body = r.get_json()
        details = body.get("error", {}).get("details")
        ok = r.status_code == 400 and body["error"]["code"] == "VALIDATION_ERROR" and details
        check(ok, f"8. {label}", f"HTTP {r.status_code} -> {json.dumps(body)}")


# --------------------------------------------------------------------------
# 9. Unexpected extra fields -> ignored, 200 with a warning
# --------------------------------------------------------------------------
def test_unexpected_fields(client):
    payload = {**SAMPLE, "favourite_colour": "blue", "churn": "No", "id": 99}
    r = post(client, payload)
    body = r.get_json()
    ok = (
        r.status_code == 200
        and body["success"] is True
        and any("favourite_colour" in w for w in body["warnings"])
    )
    check(
        ok,
        "9. unexpected fields ignored with warning",
        f"HTTP {r.status_code} -> {json.dumps(body)}",
    )


# --------------------------------------------------------------------------
# 10. Extra field must not let a client override the prediction
# --------------------------------------------------------------------------
def test_cannot_override_prediction(client):
    forced = {**SAMPLE, "churn": "Yes", "Prediction": "Yes", "Churn_Yes": 1}
    r = post(client, forced)
    body = r.get_json()
    clean = post(client, SAMPLE).get_json()
    ok = r.status_code == 200 and body["prediction"] == clean["prediction"]
    check(
        ok,
        "10. injected churn keys do not alter output",
        f"{json.dumps(body['prediction'])} == {json.dumps(clean['prediction'])}",
    )


# --------------------------------------------------------------------------
# 11. Flags accepted as 0/1 ints; dropped flags default to False
# --------------------------------------------------------------------------
def test_flag_coercion(client):
    payload = {**SAMPLE, "TechSupport_Yes": 1, "OnlineBackup_Yes": 0}
    r = post(client, payload)
    body = r.get_json()
    check(
        r.status_code == 200 and body["success"] is True,
        "11. flags as 0/1 integers",
        f"HTTP {r.status_code} -> {json.dumps(body)}",
    )


# --------------------------------------------------------------------------
# 12. No stack traces or internals in any error body
# --------------------------------------------------------------------------
def test_no_leaks(client):
    r = post(client, {"tenure": "abc"})
    text = r.get_data(as_text=True)
    leaked = [
        token
        for token in ("Traceback", "sklearn", "numpy", "pandas", "joblib",
                      "predict_customer", "build_feature_frame", "File \"")
        if token in text
    ]
    check(not leaked, "12. no internal details leaked in errors", f"leaked={leaked}")


# --------------------------------------------------------------------------
# 13. Wrong method / unknown route return JSON, not HTML
# --------------------------------------------------------------------------
def test_method_and_route_guards(client):
    # GET /predict is now the HTML prediction form; POST stays the JSON API.
    r = client.get("/predict", headers={"Accept": "application/json"})
    check(
        r.status_code == 200 and "text/html" in r.headers["Content-Type"],
        "13a. GET /predict serves the form",
        f"HTTP {r.status_code} {r.headers['Content-Type']}",
    )
    r1 = client.delete("/predict")
    check(
        r1.status_code == 405 and r1.get_json()["error"]["code"] == "METHOD_NOT_ALLOWED",
        "13b. DELETE /predict -> 405 JSON",
        f"HTTP {r1.status_code}",
    )
    r2 = client.get("/does-not-exist")
    check(
        r2.status_code == 404 and r2.get_json()["error"]["code"] == "NOT_FOUND",
        "13c. unknown route -> 404 JSON",
        f"HTTP {r2.status_code}",
    )
    r3 = client.get("/does-not-exist", headers={"Accept": "text/html"})
    check(
        r3.status_code == 404 and b"404" in r3.data,
        "13d. unknown route -> HTML page for browsers",
        f"HTTP {r3.status_code} {r3.headers['Content-Type']}",
    )


# --------------------------------------------------------------------------
# 14. Feature contract is intact (model + code agree)
# --------------------------------------------------------------------------
def test_feature_contract():
    check(len(FEATURE_NAMES) == 30, "14a. model exposes 30 features", f"got {len(FEATURE_NAMES)}")
    check(
        list(FEATURE_NAMES)[:4]
        == ["SeniorCitizen", "tenure", "MonthlyCharges", "TotalCharges"],
        "14b. training order preserved",
        f"{FEATURE_NAMES[:4]}",
    )
    check(
        set(SAMPLE) == set(FEATURE_NAMES),
        "14c. sample payload covers every feature",
        f"diff={set(SAMPLE) ^ set(FEATURE_NAMES)}",
    )


def main() -> int:
    app.config["TESTING"] = True
    with app.test_client() as client:
        a = test_valid_training_order(client)
        b = test_valid_alphabetical_order(client)
        test_key_order_independence(client, a, b)
        test_missing_optional_fields(client)
        test_empty_object(client)
        test_malformed_and_non_json(client)
        test_non_object_json(client)
        test_bad_types(client)
        test_unexpected_fields(client)
        test_cannot_override_prediction(client)
        test_flag_coercion(client)
        test_no_leaks(client)
        test_method_and_route_guards(client)
        test_feature_contract()

    width = max(len(name) for _, name, _ in RESULTS)
    print("=" * 100)
    print("POST /predict VERIFICATION")
    print("=" * 100)
    for passed, name, detail in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name.ljust(width)}  {detail}")
    print("=" * 100)
    failed = [name for passed, name, _ in RESULTS if not passed]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    print("=" * 100)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
