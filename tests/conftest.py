"""Pytest fixtures for an isolated, disposable test database.

    .\\venv\\Scripts\\python.exe -m pytest -q

Why this file exists
--------------------
`tests/test_predict_api.py` and `tests/test_frontend_api.py` were originally
written as standalone scripts with a `main()` runner. Under pytest their
functions take a `client` argument that nothing supplied, so all 20 of them
errored out. This module supplies the missing fixtures.

Isolation design (fail-closed)
------------------------------
* Tests run against a **dedicated MySQL database** (`customer_churn_db_test`),
  never `customer_churn_db`. MySQL rather than SQLite because the dashboard
  service issues MySQL-compatible aggregates and the tests assert exact
  aggregates over the full 7,032-row IBM dataset; matching the production
  engine removes any dialect risk.
* The production database name is read from `.env`. If the resolved test
  database name is the production name -- or does not look like a test
  database -- the session aborts with an error instead of running.
* The test database is created fresh, seeded from the IBM CSV, and dropped
  again at teardown. Nothing outside this file's database is ever touched.
* `os.environ["DB_NAME"]` is overridden **before** `app` is imported, because
  `config.py` reads it at import time. A belt-and-braces assertion re-checks the
  live engine URL immediately before any DDL.

Making the assertions real
--------------------------
The test modules collect their results through a `check(condition, ...)`
helper that only appends to a list; it never raises. Without help, every test
would report PASSED while asserting nothing at all. The `pytest_runtest_call`
hook below fails the test if any `check()` recorded a falsy condition, so the
existing assertions keep their meaning under pytest.
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ---------------------------------------------------------------------------
# Resolve and validate the test database BEFORE importing the application.
# ---------------------------------------------------------------------------
PRODUCTION_DB = os.getenv("DB_NAME", "")
TEST_DB = os.environ.get("TEST_DB_NAME", "customer_churn_db_test")


def _fail_closed() -> None:
    """Abort rather than run tests against anything resembling production."""
    if not TEST_DB:
        raise RuntimeError(
            "Refusing to run tests: no test database name resolved "
            "(set TEST_DB_NAME)."
        )
    if TEST_DB == PRODUCTION_DB:
        raise RuntimeError(
            f"Refusing to run tests: TEST_DB_NAME ({TEST_DB!r}) is the "
            f"production database from .env (DB_NAME={PRODUCTION_DB!r})."
        )
    if "test" not in TEST_DB.lower():
        raise RuntimeError(
            f"Refusing to run tests: test database name {TEST_DB!r} does not "
            "contain 'test'. Set TEST_DB_NAME to a clearly disposable database."
        )


_fail_closed()

# config.py reads DB_NAME at import time, so override it first.
os.environ["DB_NAME"] = TEST_DB
# Never let the application's opt-in schema gate fire during tests; this
# conftest creates the schema explicitly, against the test database only.
os.environ.pop("AUTO_CREATE_SCHEMA", None)

import pandas as pd  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app import app  # noqa: E402
from database.db import db  # noqa: E402
from flask_login import login_user  # noqa: E402
from models.customer import Customer  # noqa: E402

CSV = os.path.join(PROJECT_ROOT, "data", "WA_Fn-UseC_-Telco-Customer-Churn.csv")

# The canonical training-order payload, mirrored from
# tests/test_predict_api.py. Used by the `a` and `b` fixtures.
SAMPLE = {
    "SeniorCitizen": 0, "tenure": 12, "MonthlyCharges": 75.25,
    "TotalCharges": 900.50, "gender_Male": True, "Partner_Yes": False,
    "Dependents_Yes": False, "PhoneService_Yes": True,
    "MultipleLines_No phone service": False, "MultipleLines_Yes": True,
    "InternetService_Fiber optic": True, "InternetService_No": False,
    "OnlineSecurity_No internet service": False, "OnlineSecurity_Yes": False,
    "OnlineBackup_No internet service": False, "OnlineBackup_Yes": True,
    "DeviceProtection_No internet service": False, "DeviceProtection_Yes": False,
    "TechSupport_No internet service": False, "TechSupport_Yes": False,
    "StreamingTV_No internet service": False, "StreamingTV_Yes": True,
    "StreamingMovies_No internet service": False, "StreamingMovies_Yes": True,
    "Contract_One year": False, "Contract_Two year": False,
    "PaperlessBilling_Yes": True,
    "PaymentMethod_Credit card (automatic)": False,
    "PaymentMethod_Electronic check": True,
    "PaymentMethod_Mailed check": False,
}


def _server_engine():
    """Engine connected to the server, with no database selected."""
    return create_engine(
        f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}"
    )


def _assert_test_engine(engine) -> None:
    """Refuse to touch a database that is not the disposable test one."""
    name = engine.url.database
    if name != TEST_DB:
        raise RuntimeError(
            f"Refusing to modify {name!r}: expected the test database {TEST_DB!r}."
        )
    if name == PRODUCTION_DB:
        raise RuntimeError(f"Refusing to modify the production database {name!r}.")


def _seed_customers() -> int:
    """Load the IBM sample dataset, mirroring import_data.py's cleaning."""
    frame = pd.read_csv(CSV)
    frame["TotalCharges"] = pd.to_numeric(frame["TotalCharges"], errors="coerce")
    frame = frame.dropna()

    # Bracket access on purpose: pandas attribute access truncates camelCase
    # names at the first underscore (r.InternetService -> internetService).
    rows = [
        {
            "customer_id": r["customerID"], "gender": r["gender"],
            "senior_citizen": r["SeniorCitizen"], "partner": r["Partner"],
            "dependents": r["Dependents"], "tenure": r["tenure"],
            "phone_service": r["PhoneService"], "multiple_lines": r["MultipleLines"],
            "internet_service": r["InternetService"],
            "online_security": r["OnlineSecurity"], "online_backup": r["OnlineBackup"],
            "device_protection": r["DeviceProtection"], "tech_support": r["TechSupport"],
            "streaming_tv": r["StreamingTV"], "streaming_movies": r["StreamingMovies"],
            "contract": r["Contract"], "paperless_billing": r["PaperlessBilling"],
            "payment_method": r["PaymentMethod"],
            "monthly_charges": r["MonthlyCharges"],
            "total_charges": r["TotalCharges"], "churn": r["Churn"],
        }
        for _, r in frame.iterrows()
    ]
    db.session.execute(Customer.__table__.insert(), rows)
    db.session.commit()
    return len(rows)


@pytest.fixture(scope="session", autouse=True)
def _isolated_database():
    """Create, seed and later drop the disposable test database."""
    server = _server_engine()
    with server.begin() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{TEST_DB}`"))
        conn.execute(
            text(
                f"CREATE DATABASE `{TEST_DB}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        )

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{TEST_DB}"
    )

    with app.app_context():
        _assert_test_engine(db.engine)
        # Drop every table the models describe, then recreate from the models.
        db.drop_all()
        db.create_all()
        seeded = _seed_customers()
        total = db.session.execute(
            text("SELECT COUNT(*) FROM customers")
        ).scalar()
        assert total == seeded == 7032, (
            f"expected 7032 seeded customers, found {total}"
        )
        _seed_tenant()

    yield

    with app.app_context():
        _assert_test_engine(db.engine)
        db.session.remove()
        db.drop_all()
    with server.begin() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{TEST_DB}`"))
    server.dispose()


# ----------------------------------------------------------------------
# Tenant fixtures
#
# The seeded IBM rows have company_id IS NULL, so they are sample data only.
# Company A and Company B each own their own rows and must never see the
# other's, nor the IBM rows.
# ----------------------------------------------------------------------
COMPANY_A_SLUG = "alpha-telecom"
COMPANY_B_SLUG = "beta-telecom"

# A strong, clearly-synthetic password. Not a real credential anywhere.
TEST_PASSWORD = "Test-Only-Passw0rd!2026"


def _make_company(slug: str, name: str, domain: str):
    from models.company import Company
    from models.user import ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER, User

    company = Company(name=name, slug=slug, is_active=True)
    db.session.add(company)
    db.session.flush()

    users = {}
    for role, label in ((ROLE_ADMIN, "admin"), (ROLE_ANALYST, "analyst"), (ROLE_VIEWER, "viewer")):
        user = User(
            full_name=f"{name} {role}",
            email=f"{label}@{domain}",
            role=role,
            company_id=company.id,
            is_active_flag=True,
        )
        user.set_password(TEST_PASSWORD)
        db.session.add(user)
        users[role] = user

    # Two customers owned by this company, clearly distinct from IBM rows.
    company_customers = [
        (f"{slug.upper()}-0001", "One year", 40),
        (f"{slug.upper()}-0002", "Two year", 60),
    ]
    for ref, contract, tenure in company_customers:
        db.session.execute(
            Customer.__table__.insert(),
            [{
                "company_id": company.id,
                "source": "company_import",
                "customer_id": ref,
                "gender": "Male",
                "senior_citizen": 0,
                "partner": "Yes",
                "dependents": "No",
                "tenure": tenure,
                "phone_service": "Yes",
                "multiple_lines": "No",
                "internet_service": "DSL",
                "online_security": "Yes",
                "online_backup": "No",
                "device_protection": "No",
                "tech_support": "Yes",
                "streaming_tv": "No",
                "streaming_movies": "No",
                "contract": contract,
                "paperless_billing": "No",
                "payment_method": "Credit card (automatic)",
                "monthly_charges": 55.5,
                "total_charges": 2200.0,
                "churn": None,   # no actual outcome yet for imported data
            }],
        )
    db.session.commit()
    return company, users


def _seed_tenant() -> dict:
    """Create two independent companies with one customer pair each."""
    a_company, a_users = _make_company(COMPANY_A_SLUG, "Alpha Telecom", "alphatelecom.example")
    b_company, b_users = _make_company(COMPANY_B_SLUG, "Beta Telecom", "bettatelecom.example")

    # A separate deactivated account, so the real Viewer stays intact.
    from models.user import ROLE_VIEWER, User

    inactive = User(
        full_name="Alpha Telecom Deactivated",
        email="inactive@alphatelecom.example",
        role=ROLE_VIEWER,
        company_id=a_company.id,
        is_active_flag=False,
    )
    inactive.set_password(TEST_PASSWORD)
    db.session.add(inactive)
    db.session.commit()

    return {
        "a_company": a_company,
        "a_users": a_users,
        "b_company": b_company,
        "b_users": b_users,
    }


TENANTS: dict = {}


def login_via_form(client, email: str, password: str = TEST_PASSWORD):
    """Sign in through the real /login endpoint.

    Going over HTTP rather than poking session internals means the fixtures
    exercise the genuine login path, including Flask-Login and the limiter.
    """
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def logout_via_form(client):
    """Sign out through the real /logout endpoint (POST, CSRF-protected)."""
    return client.post("/logout", follow_redirects=False)


@pytest.fixture(scope="session")
def tenants(_isolated_database):
    """Company A / Company B handles created by _seed_tenant()."""
    global TENANTS
    if not TENANTS:
        with app.app_context():
            from models.company import Company
            from models.user import User

            a_company = db.session.execute(
                text("SELECT id FROM companies WHERE slug = :s"),
                {"s": COMPANY_A_SLUG},
            ).scalar_one()
            b_company = db.session.execute(
                text("SELECT id FROM companies WHERE slug = :s"),
                {"s": COMPANY_B_SLUG},
            ).scalar_one()
            TENANTS["a_company_id"] = int(a_company)
            TENANTS["b_company_id"] = int(b_company)
    return TENANTS


@pytest.fixture()
def client(_isolated_database):
    """Test client signed in as Company A's Admin.

    Existing suites assert on the 7,032 IBM rows, which is the demo scope an
    Admin is permitted to read.
    """
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        response = login_via_form(test_client, "admin@alphatelecom.example")
        assert response.status_code == 302, (
            f"admin login expected a redirect, got HTTP {response.status_code}"
        )
        yield test_client


@pytest.fixture()
def anon_client(_isolated_database):
    """A client with no session at all."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture()
def viewer_client(_isolated_database):
    app.config["TESTING"] = True
    with app.test_client() as c:
        login_via_form(c, "viewer@alphatelecom.example")
        yield c


@pytest.fixture()
def analyst_client(_isolated_database):
    app.config["TESTING"] = True
    with app.test_client() as c:
        login_via_form(c, "analyst@alphatelecom.example")
        yield c


@pytest.fixture()
def client_b(_isolated_database):
    """A session belonging to a different company (Beta Telecom)."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        login_via_form(c, "admin@bettatelecom.example")
        yield c


@pytest.fixture()
def inactive_client(_isolated_database):
    """No session; used to attempt login with a deactivated account."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c




@pytest.fixture()
def a(client):
    """Prediction for the canonical payload in training key order."""
    return client.post("/predict", json=SAMPLE).get_json()["prediction"]


@pytest.fixture()
def b(client):
    """Prediction for the identical payload with keys alphabetised."""
    import json

    alphabetised = dict(sorted(SAMPLE.items()))
    response = client.post(
        "/predict",
        data=json.dumps(alphabetised),
        content_type="application/json",
    )
    return response.get_json().get("prediction")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Fail a test if any of its check() calls recorded a falsy condition.

    The test modules' `check()` helper only appends to a RESULTS list, so a
    plain pytest run would report success even when every assertion failed.
    """
    module = getattr(item, "module", None)
    results = getattr(module, "RESULTS", None) if module else None
    start = len(results) if results is not None else 0

    yield

    if results is None:
        return

    failures = [r for r in results[start:] if not r[0]]
    if failures:
        pytest.fail(
            "\n".join(
                f"  FAILED: {name}\n          {detail}" for _, name, detail in failures
            ),
            pytrace=False,
        )
