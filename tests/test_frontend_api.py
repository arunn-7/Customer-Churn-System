"""Tests for the frontend layer: schema, dashboard APIs, mapping fidelity.

    .\\venv\\Scripts\\python.exe tests\\test_frontend_api.py

The centrepiece is test_group_2 -- it proves the friendly field names map onto
exactly the same 30 columns the training pipeline produced, by replaying the real
CSV through `ml.preprocess.preprocess_data` and comparing every column.
"""

import json
import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from app import app  # noqa: E402
from ml.predict import FEATURE_NAMES, model  # noqa: E402
from ml.preprocess import preprocess_data  # noqa: E402
from ml.schema import FIELDS_BY_KEY, to_model_features  # noqa: E402

CSV = os.path.join(PROJECT_ROOT, "data", "WA_Fn-UseC_-Telco-Customer-Churn.csv")

RESULTS: list[tuple[bool, str, str]] = []


def check(condition: bool, name: str, detail: str = "") -> None:
    RESULTS.append((bool(condition), name, detail))


CUSTOMER = {
    "SeniorCitizen": 0,
    "tenure": 3,
    "gender": "Female",
    "Partner": "No",
    "Dependents": "No",
    "Contract": "Month-to-month",
    "PaymentMethod": "Electronic check",
    "PaperlessBilling": "Yes",
    "MonthlyCharges": 88.0,
    "TotalCharges": 260.0,
    "PhoneService": "Yes",
    "MultipleLines": "Yes",
    "InternetService": "Fiber optic",
    "OnlineSecurity": "No",
    "OnlineBackup": "No",
    "DeviceProtection": "No",
    "TechSupport": "No",
    "StreamingTV": "Yes",
    "StreamingMovies": "No",
}


# ---------------------------------------------------------------------------
# 1. Mapping fidelity against the real training pipeline
# ---------------------------------------------------------------------------
def test_mapping_fidelity():
    if not os.path.exists(CSV):
        check(False, "1. mapping fidelity", "dataset CSV not found - skipped")
        return

    processed = preprocess_data(pd.read_csv(CSV))
    features = processed.drop("Churn_Yes", axis=1)

    # Re-apply the same row filtering so indices line up.
    clean = pd.read_csv(CSV)
    clean["TotalCharges"] = pd.to_numeric(clean["TotalCharges"], errors="coerce")
    clean = clean.dropna().reset_index(drop=True)

    check(
        list(features.columns) == FEATURE_NAMES,
        "1a. pipeline columns == model.feature_names_in_",
        f"pipeline={len(features.columns)} model={len(FEATURE_NAMES)}",
    )

    categorical = [k for k in FIELDS_BY_KEY if k not in ("SeniorCitizen", "tenure",
                                                         "MonthlyCharges", "TotalCharges")]

    mismatches = []
    for i in range(0, len(clean), 53):
        record = clean.iloc[i]
        friendly = {k: record[k] for k in categorical}
        friendly.update(
            SeniorCitizen=int(record["SeniorCitizen"]),
            tenure=int(record["tenure"]),
            MonthlyCharges=float(record["MonthlyCharges"]),
            TotalCharges=float(record["TotalCharges"]),
        )
        mapped = to_model_features(friendly)
        expected = features.iloc[i]
        for column in FEATURE_NAMES:
            if float(mapped[column]) != float(expected[column]):
                mismatches.append((i, column, mapped[column], expected[column]))

    check(
        not mismatches,
        "1b. friendly mapping reproduces the pipeline exactly",
        f"{len(clean)//53 + 1} rows sampled, {len(mismatches)} mismatches"
        + (f" first={mismatches[0]}" if mismatches else ""),
    )

    # Probability parity proves the end-to-end path, not just column equality.
    first = clean.iloc[0]
    friendly = {k: first[k] for k in categorical}
    friendly.update(SeniorCitizen=int(first["SeniorCitizen"]), tenure=int(first["tenure"]),
                    MonthlyCharges=float(first["MonthlyCharges"]),
                    TotalCharges=float(first["TotalCharges"]))
    mapped_frame = pd.DataFrame([to_model_features(friendly)], columns=FEATURE_NAMES).astype(float)
    direct_frame = features.iloc[[0]][FEATURE_NAMES].astype(float)
    p_mapped = float(model.predict_proba(mapped_frame)[0][1])
    p_direct = float(model.predict_proba(direct_frame)[0][1])
    check(p_mapped == p_direct, "1c. predicted probability identical", f"{p_mapped!r} == {p_direct!r}")


# ---------------------------------------------------------------------------
# 2. Schema endpoint
# ---------------------------------------------------------------------------
def test_schema_endpoint(client):
    r = client.get("/predict/schema")
    body = r.get_json()
    fields = body.get("fields", [])

    check(r.status_code == 200 and body["success"] is True, "2a. GET /predict/schema", f"HTTP {r.status_code}")
    check(len(fields) == 19, "2b. schema exposes 19 form fields", f"got {len(fields)}")
    check(
        body.get("feature_count") == 30,
        "2c. schema reports the model's 30 features",
        f"got {body.get('feature_count')}",
    )

    # No technical dummy names may leak into the UI contract.
    leaked = [f["key"] for f in fields if "_Yes" in f["key"] or "No internet service" in f["key"]
              or " (automatic)" in f["key"] or "Month-to-month" in f["key"]]
    check(not leaked, "2d. no dummy-column names exposed to users", f"leaked={leaked}")

    # Options must match the CSV exactly, or predictions would be wrong.
    csv = pd.read_csv(CSV, nrows=2000)
    bad = []
    for field in fields:
        if field["type"] != "select" or field["key"] == "SeniorCitizen":
            continue
        csv_values = {str(v) for v in csv[field["key"]].dropna().unique()}
        schema_values = {str(o["value"]) for o in field["options"]}
        if not csv_values <= schema_values:
            bad.append((field["key"], sorted(csv_values - schema_values)))
    check(not bad, "2e. every option value exists in the CSV", f"bad={bad}")

    check(
        all({"key", "label", "type", "group"} <= set(f) for f in fields),
        "2f. each field has key/label/type/group",
    )


# ---------------------------------------------------------------------------
# 3. Friendly-payload prediction
# ---------------------------------------------------------------------------
def test_friendly_prediction(client):
    r = client.post("/predict", json=CUSTOMER)
    body = r.get_json()
    check(
        r.status_code == 200 and body["success"] is True,
        "3a. POST /predict accepts friendly field names",
        f"HTTP {r.status_code} {json.dumps(body.get('prediction'))}",
    )
    check(
        body.get("warnings") == [],
        "3b. no warnings for a complete friendly payload",
        f"{body.get('warnings')}",
    )

    r2 = client.post("/predict/explain", json=CUSTOMER)
    body2 = r2.get_json()
    check(
        body2["prediction"] == body["prediction"],
        "3c. /predict and /predict/explain agree",
        f"{json.dumps(body['prediction'])} vs {json.dumps(body2['prediction'])}",
    )
    check(
        body2["risk"]["level"] in ("low", "medium", "high"),
        "3d. risk band returned",
        f"{body2['risk']['level']}",
    )
    check(
        len(body2["factors"]) > 0 and all("impact" in f for f in body2["factors"]),
        "3e. contributing factors returned",
        f"{len(body2['factors'])} factors, top={body2['factors'][0]['label'] if body2['factors'] else None}",
    )

    # Baseline categories must be handled correctly, not assumed.
    for field, value, expect_label in (
        ("InternetService", "DSL", "DSL"),
        ("PaymentMethod", "Bank transfer (automatic)", "Bank transfer (automatic)"),
        ("MultipleLines", "No", "No"),
        ("Contract", "Month-to-month", "Month to month"),
    ):
        payload = dict(CUSTOMER)
        payload[field] = value
        resp = client.post("/predict", json=payload)
        check(
            resp.status_code == 200,
            f"3f. baseline category accepted: {field}={expect_label}",
            f"HTTP {resp.status_code}",
        )


# ---------------------------------------------------------------------------
# 4. Friendly-payload validation
# ---------------------------------------------------------------------------
def test_friendly_validation(client):
    incomplete = {k: v for k, v in CUSTOMER.items() if k != "Contract"}
    r = client.post("/predict", json=incomplete)
    body = r.get_json()
    check(
        r.status_code == 400 and body["error"]["code"] == "VALIDATION_ERROR",
        "4a. missing friendly field -> 400",
        f"HTTP {r.status_code}",
    )
    check(
        any(d.get("field") == "Contract Type" for d in body["error"].get("details", [])),
        "4b. error names the field in human terms",
        f"{body['error'].get('details')}",
    )

    r2 = client.post("/predict", json={})
    check(
        r2.status_code == 400,
        "4c. empty object -> 400",
        f"HTTP {r2.status_code}",
    )

    bad = dict(CUSTOMER)
    bad["tenure"] = 999
    r3 = client.post("/predict", json=bad)
    check(
        r3.status_code == 400,
        "4d. out-of-range tenure -> 400",
        f"HTTP {r3.status_code} {r3.get_json()['error']['details'][:1]}",
    )

    bad2 = dict(CUSTOMER)
    bad2["Contract"] = "Not a contract"
    r4 = client.post("/predict", json=bad2)
    check(
        r4.status_code == 400,
        "4e. invalid option -> 400",
        f"HTTP {r4.status_code}",
    )

    r5 = client.post("/predict/explain", json={})
    check(
        r5.status_code == 400,
        "4f. /predict/explain rejects empty object",
        f"HTTP {r5.status_code}",
    )


# ---------------------------------------------------------------------------
# 5. Dashboard APIs
# ---------------------------------------------------------------------------
def test_stats_endpoint(client):
    r = client.get("/api/stats")
    body = r.get_json()
    stats = body.get("stats", {})

    check(r.status_code == 200, "5a. GET /api/stats", f"HTTP {r.status_code}")
    check(stats.get("total_customers") == 7032, "5b. total customers == 7032", f"{stats.get('total_customers')}")
    check(
        stats.get("total_customers") == stats.get("churned", 0) + stats.get("retained", 0),
        "5c. churned + retained == total",
        f"{stats.get('churned')} + {stats.get('retained')} = {stats.get('total_customers')}",
    )
    check(
        abs(stats.get("churn_rate", 0) - (stats.get("churned", 0) / stats["total_customers"] * 100)) < 0.01,
        "5d. churn rate consistent",
        f"{stats.get('churn_rate')}%",
    )


def test_analytics_endpoint(client):
    r = client.get("/api/analytics")
    data = r.get_json().get("analytics", {})
    check(r.status_code == 200, "6a. GET /api/analytics", f"HTTP {r.status_code}")

    for key in ("by_contract", "by_internet_service", "by_payment_method",
                "by_tech_support", "by_tenure_band", "by_charges_band"):
        rows = data.get(key, [])
        ok = bool(rows) and all(
            {"label", "count", "churned", "churn_rate"} <= set(row) for row in rows
        )
        check(ok, f"6b. analytics.{key} well formed", f"{len(rows)} rows")

    tenure_total = sum(row["count"] for row in data.get("by_tenure_band", []))
    check(tenure_total == 7032, "6c. tenure bands cover all customers", f"{tenure_total}")

    contract = {row["label"]: row for row in data.get("by_contract", [])}
    check(
        contract.get("Month-to-month", {}).get("churn_rate", 0)
        > contract.get("Two year", {}).get("churn_rate", 99),
        "6d. month-to-month churns more than two-year",
        f"M2M={contract.get('Month-to-month',{}).get('churn_rate')} "
        f"2Y={contract.get('Two year',{}).get('churn_rate')}",
    )


def test_customers_endpoint(client):
    r = client.get("/api/customers?per_page=10")
    body = r.get_json()
    check(
        len(body["customers"]) == 10 and body["pagination"]["total"] == 7032,
        "7a. pagination totals correct",
        f"{body['pagination']}",
    )

    r2 = client.get("/api/customers?search=4489")
    total = r2.get_json()["pagination"]["total"]
    check(total >= 1, "7b. search finds a known customer id", f"{total} hits")

    r3 = client.get("/api/customers?search=4489-SNOJF")
    row = r3.get_json()["customers"][0]
    check(
        row["customer_id"] == "4489-SNOJF" and row["tenure"] == 35,
        "7c. exact search returns the right record",
        f"{row['customer_id']} tenure={row['tenure']}",
    )

    r4 = client.get("/api/customers?churn=Yes&per_page=100")
    body4 = r4.get_json()
    check(
        body4["pagination"]["total"] == 1869
        and all(c["churn"] == "Yes" for c in body4["customers"]),
        "7d. churn filter correct",
        f"{body4['pagination']['total']} churned, all Yes",
    )

    r5 = client.get("/api/customers?sort=tenure&order=desc&per_page=5")
    tenures = [c["tenure"] for c in r5.get_json()["customers"]]
    check(tenures == sorted(tenures, reverse=True), "7e. descending sort", f"{tenures}")

    r6 = client.get("/api/customers?page=2&per_page=10")
    page1 = [c["customer_id"] for c in client.get("/api/customers?page=1&per_page=10").get_json()["customers"]]
    page2 = [c["customer_id"] for c in r6.get_json()["customers"]]
    check(not set(page1) & set(page2), "7f. pages do not overlap", f"{len(page1)} vs {len(page2)}")

    # Guard against SQL injection through the sort/search parameters.
    r7 = client.get("/api/customers?sort=DROP+TABLE+customers")
    check(
        r7.status_code == 200,
        "7g. bogus sort falls back safely",
        f"HTTP {r7.status_code}",
    )
    r8 = client.get("/api/customers?search='+OR+'1'='1")
    check(
        r8.get_json()["pagination"]["total"] < 7032,
        "7h. SQL metacharacters in search are not executed",
        f"{r8.get_json()['pagination']['total']} hits",
    )

    r9 = client.get("/api/customers/NOT-A-CUSTOMER")
    check(
        r9.status_code == 404 and r9.get_json()["error"]["code"] == "NOT_FOUND",
        "7i. unknown customer -> 404",
        f"HTTP {r9.status_code}",
    )


# ---------------------------------------------------------------------------
# 6. HTML pages
# ---------------------------------------------------------------------------
def test_pages(client):
    for path, marker in (("/", "Dashboard"), ("/predict", "Customer details"),
                         ("/customers", "Search and browse")):
        r = client.get(path)
        ok = r.status_code == 200 and b"ChurnIQ" in r.data and marker.encode() in r.data
        check(ok, f"8. GET {path} renders", f"HTTP {r.status_code}")

    for asset in ("css/style.css", "js/api.js", "js/charts.js", "js/dashboard.js",
                  "js/predict.js", "js/customers.js", "js/nav.js"):
        r = client.get(f"/static/{asset}")
        check(r.status_code == 200, f"8. static asset {asset}", f"HTTP {r.status_code}")

    r = client.get("/does-not-exist", headers={"Accept": "text/html"})
    check(r.status_code == 404 and b"Page not found" in r.data,
          "8. browser 404 page", f"HTTP {r.status_code}")


def main() -> int:
    app.config["TESTING"] = True
    with app.test_client() as client:
        test_mapping_fidelity()
        test_schema_endpoint(client)
        test_friendly_prediction(client)
        test_friendly_validation(client)
        test_stats_endpoint(client)
        test_analytics_endpoint(client)
        test_customers_endpoint(client)
        test_pages(client)

    width = max(len(name) for _, name, _ in RESULTS)
    print("=" * 104)
    print("FRONTEND / MAPPING VERIFICATION")
    print("=" * 104)
    for passed, name, detail in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name.ljust(width)}  {detail}")
    print("=" * 104)
    failed = [name for passed, name, _ in RESULTS if not passed]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILED: " + "; ".join(failed))
    print("=" * 104)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
