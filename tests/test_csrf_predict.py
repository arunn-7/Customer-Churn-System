"""CSRF regression tests for the prediction endpoints.

    .\\venv\\Scripts\\python.exe -m pytest tests\\test_csrf_predict.py -v

Background
----------
The JavaScript prediction form POSTs JSON to /predict without a CSRF token,
relying on a server-side exemption. Those exemptions were configured with the
short endpoint names ("predict"). Flask registers blueprint routes with the
blueprint name as a prefix ("predict.predict"), so every lookup returned None,
zero exemptions were registered, and the form failed with:

    "Your session expired or the form was not submitted correctly."

These tests pin the contract so it cannot silently regress:

* every configured exemption must resolve to a real view;
* the JSON prediction endpoints must work without a token when authenticated;
* login/register/logout must remain CSRF-protected;
* prediction behaviour itself (feature ordering, output shape) is unchanged.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app, csrf  # noqa: E402
from config import Config  # noqa: E402

PW = "Test-Only-Passw0rd!2026"
TOKEN_RE = re.compile(r'name="csrf_token" value="([^"]+)"')

FRIENDLY = {
    "SeniorCitizen": 0, "tenure": 3, "gender": "Female", "Partner": "No",
    "Dependents": "No", "Contract": "Month-to-month",
    "PaymentMethod": "Electronic check", "PaperlessBilling": "Yes",
    "MonthlyCharges": 88.0, "TotalCharges": 260.0, "PhoneService": "Yes",
    "MultipleLines": "Yes", "InternetService": "Fiber optic",
    "OnlineSecurity": "No", "OnlineBackup": "No", "DeviceProtection": "No",
    "TechSupport": "No", "StreamingTV": "Yes", "StreamingMovies": "No",
}


@pytest.fixture()
def csrf_on():
    """Run the request with CSRF enforcement active, as in production."""
    previous = app.config["WTF_CSRF_ENABLED"]
    app.config["WTF_CSRF_ENABLED"] = True
    yield
    app.config["WTF_CSRF_ENABLED"] = previous


def _login(c, email="admin@alphatelecom.example"):
    """Sign in through the real form, supplying a valid CSRF token."""
    token = TOKEN_RE.search(c.get("/login").get_data(as_text=True)).group(1)
    return c.post("/login", data={
        "email": email, "password": PW, "csrf_token": token,
    }, follow_redirects=False)


# =====================================================================
# 1. Exemption configuration (the regression itself)
# =====================================================================
def test_every_exempt_endpoint_resolves_to_a_real_view():
    """A name that does not resolve silently disables its exemption."""
    for name in Config.CSRF_EXEMPT_ENDPOINTS:
        assert name in app.view_functions, (
            f"CSRF_EXEMPT_ENDPOINTS contains {name!r}, which is not a "
            f"registered endpoint. Flask prefixes blueprint routes with the "
            f"blueprint name."
        )


def test_exemptions_are_actually_registered():
    assert len(csrf._exempt_views) >= len(Config.CSRF_EXEMPT_ENDPOINTS)
    for name in Config.CSRF_EXEMPT_ENDPOINTS:
        view = app.view_functions[name]
        location = ".".join((view.__module__, view.__name__))
        assert location in csrf._exempt_views, f"{name} was not exempted"


def test_auth_endpoints_are_never_exempt():
    for name in ("auth.login", "auth.logout", "auth.register_company_view"):
        assert name not in Config.CSRF_EXEMPT_ENDPOINTS
        view = app.view_functions[name]
        location = ".".join((view.__module__, view.__name__))
        assert location not in csrf._exempt_views


def test_prediction_endpoints_are_exempt():
    for name in ("predict.predict", "predict.predict_explain"):
        assert name in Config.CSRF_EXEMPT_ENDPOINTS


def test_app_startup_rejects_unknown_exemption(monkeypatch):
    """A bad name must raise at import time, not fail silently at runtime."""
    import importlib
    import app as app_module

    original = app_module.Config.CSRF_EXEMPT_ENDPOINTS
    try:
        app_module.Config.CSRF_EXEMPT_ENDPOINTS = (
            *original, "definitely.not.a.real.endpoint",
        )
        with pytest.raises(RuntimeError, match="do not exist"):
            importlib.reload(app_module)
    finally:
        # Restore so later tests use a working app instance.
        app_module.Config.CSRF_EXEMPT_ENDPOINTS = original
        importlib.reload(app_module)


# =====================================================================
# 2. Prediction works without a token (the reported bug)
# =====================================================================
def test_prediction_succeeds_without_csrf_token_when_authenticated(csrf_on):
    """The exact flow of the /predict page: JSON POST, no CSRF token."""
    with app.test_client() as c:
        assert _login(c).status_code == 302

        r = c.post("/predict", json=FRIENDLY)
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        body = r.get_json()
        assert body["success"] is True
        assert body["prediction"]["churn"] in ("Yes", "No")
        assert 0.0 <= body["prediction"]["churn_probability"] <= 100.0


def test_prediction_explain_succeeds_without_token(csrf_on):
    with app.test_client() as c:
        _login(c)
        r = c.post("/predict/explain", json=FRIENDLY)
        assert r.status_code == 200
        body = r.get_json()
        assert body["risk"]["level"] in ("low", "medium", "high")
        assert isinstance(body["factors"], list)


def test_prediction_requires_authentication(csrf_on):
    """Exempt from CSRF does NOT mean exempt from login."""
    with app.test_client() as c:
        assert c.post("/predict", json=FRIENDLY).status_code == 401
        assert c.post("/predict/explain", json=FRIENDLY).status_code == 401


def test_key_order_still_does_not_matter(csrf_on):
    """Feature ordering fix must survive the CSRF change."""
    import json
    with app.test_client() as c:
        _login(c)
        first = c.post("/predict", json=FRIENDLY).get_json()["prediction"]
        alphabetised = json.dumps(dict(sorted(FRIENDLY.items())))
        second = c.post(
            "/predict", data=alphabetised, content_type="application/json",
        ).get_json()["prediction"]
        assert first == second


# =====================================================================
# 3. Authentication endpoints stay CSRF-protected
# =====================================================================
def test_login_without_token_is_rejected(csrf_on):
    with app.test_client() as c:
        r = c.post("/login", data={
            "email": "admin@alphatelecom.example", "password": PW,
        })
        assert r.status_code == 400


def test_login_with_valid_token_succeeds(csrf_on):
    with app.test_client() as c:
        assert _login(c).status_code == 302


def test_login_with_wrong_token_is_rejected(csrf_on):
    with app.test_client() as c:
        r = c.post("/login", data={
            "email": "admin@alphatelecom.example", "password": PW,
            "csrf_token": "not-a-real-token",
        })
        assert r.status_code == 400


def test_logout_without_token_is_rejected(csrf_on):
    with app.test_client() as c:
        _login(c)
        assert c.post("/logout").status_code == 400


def test_logout_with_token_succeeds(csrf_on):
    with app.test_client() as c:
        _login(c)
        token = TOKEN_RE.search(c.get("/").get_data(as_text=True)).group(1)
        assert c.post("/logout", data={"csrf_token": token}).status_code == 302


def test_registration_without_token_is_rejected(csrf_on):
    with app.test_client() as c:
        r = c.post("/register", data={
            "company_name": "Csrf Test Co", "full_name": "Cee See",
            "email": "csrf@csrftest.example", "password": PW,
            "confirm_password": PW,
        })
        assert r.status_code == 400


def test_expired_token_is_rejected(csrf_on, monkeypatch):
    """A token older than WTF_CSRF_TIME_LIMIT must not be accepted."""
    import itsdangerous.timed
    import time as _time

    # itsdangerous stamps tokens from the global time module, so capture the
    # real function BEFORE patching or the replacement would call itself.
    real_time = _time.time

    with app.test_client() as c:
        token = TOKEN_RE.search(c.get("/login").get_data(as_text=True)).group(1)
        # Push the clock forward so the token we just issued is past its limit.
        monkeypatch.setattr(
            itsdangerous.timed.time, "time", lambda: real_time() + 7200)
        r = c.post("/login", data={
            "email": "admin@alphatelecom.example", "password": PW,
            "csrf_token": token,
        })
        assert r.status_code == 400


# =====================================================================
# 4. Configuration invariants
# =====================================================================
def test_csrf_still_enabled_by_default():
    assert Config.WTF_CSRF_ENABLED is True


def test_csrf_time_limit_unchanged():
    assert Config.WTF_CSRF_TIME_LIMIT == 3600


def test_secret_key_untouched():
    """The fix must not have regenerated or rotated SECRET_KEY."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    assert os.getenv("SECRET_KEY"), "SECRET_KEY must remain set in .env"


def test_model_untouched():
    """ml/model.pkl must be byte-identical."""
    import hashlib
    path = os.path.join(PROJECT_ROOT, "ml", "model.pkl")
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert digest == (
        "1d9a2a15e03d9a8628f89910ffe8eaa67d6c923adf2cc9f8f722bf97767f0e18"
    )


def test_auto_create_schema_still_off():
    """The fix must not enable automatic schema creation."""
    assert os.environ.get("AUTO_CREATE_SCHEMA", "").lower() not in (
        "1", "true", "yes", "on"
    )
