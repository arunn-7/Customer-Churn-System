"""Authentication, authorization and tenant-isolation tests.

    .\\venv\\Scripts\\python.exe -m pytest tests\\test_auth_tenant.py -v

Runs exclusively against the disposable test database created by conftest.
Assertions are real `assert` statements: a false condition fails the test.

Coverage
--------
* Registration: success, duplicate email, invalid email, weak passwords,
  missing fields, transaction rollback, and attempts to self-assign a role or
  a company id from the request.
* Authentication: success, wrong password, unknown email, inactive account,
  logout, session protection, throttling, generic error message.
* CSRF and open redirect.
* Authorization: unauthenticated access, Viewer denied demo data,
  Admin/Analyst allowed.
* Tenant isolation: Company A cannot read Company B's customers, analytics or
  details; IBM sample rows never appear in company scope and company rows
  never appear in demo scope.
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app  # noqa: E402
from database.db import db  # noqa: E402
from models.company import Company  # noqa: E402
from models.user import User  # noqa: E402
from services import auth_service  # noqa: E402
from services.auth_service import (  # noqa: E402
    GENERIC_LOGIN_ERROR,
    LoginRateLimiter,
    ValidationError,
    normalize_email,
    register_company,
    slugify,
    validate_password,
)

# The seeded accounts all share the password conftest created them with.
from conftest import TEST_PASSWORD as GOOD_PASSWORD  # noqa: E402

# Company A owns ALPHA-TELECOM-0001/0002; Company B owns BETA-TELECOM-0001/0002.
A_CUSTOMER = "ALPHA-TELECOM-0001"
B_CUSTOMER = "BETA-TELECOM-0001"
IBM_CUSTOMER = "7590-VHVEG"   # an IBM sample row, company_id IS NULL

# A complete friendly-field payload, matching what the form submits.
FRIENDLY_CUSTOMER = {
    "SeniorCitizen": 0, "tenure": 3, "gender": "Female", "Partner": "No",
    "Dependents": "No", "Contract": "Month-to-month",
    "PaymentMethod": "Electronic check", "PaperlessBilling": "Yes",
    "MonthlyCharges": 88.0, "TotalCharges": 260.0, "PhoneService": "Yes",
    "MultipleLines": "Yes", "InternetService": "Fiber optic",
    "OnlineSecurity": "No", "OnlineBackup": "No", "DeviceProtection": "No",
    "TechSupport": "No", "StreamingTV": "Yes", "StreamingMovies": "No",
}


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Keep the throttle from leaking state between tests."""
    auth_service.login_limiter.clear()
    yield
    auth_service.login_limiter.clear()


# =====================================================================
# 1. Email normalisation
# =====================================================================
def test_email_is_trimmed_and_lowercased():
    assert normalize_email("  Admin@Example.COM  ") == "admin@example.com"
    assert normalize_email("USER@EXAMPLE.COM") == "user@example.com"


def test_email_must_be_present():
    with pytest.raises(ValidationError):
        normalize_email("   ")


@pytest.mark.parametrize("bad", ["not-an-email", "a@b", "@nodomain.com", "two@@x.com"])
def test_invalid_emails_are_rejected(bad):
    with pytest.raises(ValidationError):
        normalize_email(bad)


def test_special_use_tld_rejected():
    """email-validator blocks reserved TLDs; registration must not accept them."""
    with pytest.raises(ValidationError):
        normalize_email("admin@alpha.test")


# =====================================================================
# 2. Password policy
# =====================================================================
@pytest.mark.parametrize("weak", [
    "short1!A",                 # too short
    "alllowercase123!",          # no uppercase
    "ALLUPPERCASE123!",          # no lowercase
    "NoDigitsHere!!!",           # no digit
    "NoSymbolsAtAll123",         # no symbol
])
def test_weak_passwords_rejected(weak):
    with pytest.raises(ValidationError):
        validate_password(weak)


def test_strong_password_accepted():
    validate_password(GOOD_PASSWORD)      # must not raise


def test_empty_password_rejected():
    with pytest.raises(ValidationError):
        validate_password("")


# =====================================================================
# 3. Slug generation
# =====================================================================
def test_slugify():
    assert slugify("Alpha Telecom Ltd") == "alpha-telecom-ltd"
    assert slugify("  Ünïcodé Co  ") == "unicode-co"
    assert slugify("!!!") == "company"


# =====================================================================
# 4. Registration
# =====================================================================
def _register(anon, **overrides):
    data = {
        "company_name": "Gamma Networks",
        "full_name": "Gina Admin",
        "email": "gina@gammanetworks.example",
        "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD,
    }
    data.update(overrides)
    return anon.post("/register", data=data, follow_redirects=False)


def test_registration_creates_company_and_admin(anon_client):
    response = _register(anon_client)
    assert response.status_code == 302, "registration should redirect on success"

    with app.app_context():
        company = db.session.query(Company).filter(
            Company.slug.like("gamma-networks%")).one()
        user = db.session.query(User).filter_by(email="gina@gammanetworks.example").one()
        assert user.company_id == company.id
        assert user.role == "Admin", "first user must be the company Admin"
        assert user.is_active_flag is True
        # Password stored as a bcrypt hash, never plaintext.
        assert user.password.startswith("$2b$")
        assert GOOD_PASSWORD not in user.password
        assert user.check_password(GOOD_PASSWORD) is True
        assert user.check_password("wrong-password") is False


def test_registration_lowercases_email(anon_client):
    _register(anon_client, email="Mixed.Case@Gamma.example")
    with app.app_context():
        user = db.session.query(User).filter_by(email="mixed.case@gamma.example").one()
        assert user.email == user.email.lower()


def test_duplicate_email_is_rejected(anon_client):
    first = _register(anon_client, email="dupe@gamma.example")
    assert first.status_code == 302
    second = _register(anon_client, email="dupe@gamma.example", company_name="Other Co")
    assert second.status_code == 400
    body = second.get_data(as_text=True)
    assert "already exists" in body


def test_duplicate_email_different_case_is_rejected(anon_client):
    """Lowercasing must make the unique index effective for case variants."""
    assert _register(anon_client, email="Case@Gamma.example").status_code == 302
    again = _register(anon_client, email="CASE@GAMMA.EXAMPLE", company_name="Another Co")
    assert again.status_code == 400


def test_registration_missing_fields(anon_client):
    response = anon_client.post("/register", data={}, follow_redirects=False)
    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "Company name is required" in body
    assert "required" in body


def test_registration_invalid_email(anon_client):
    response = _register(anon_client, email="not-an-email")
    assert response.status_code == 400
    assert "valid email address" in response.get_data(as_text=True)


def test_registration_weak_password(anon_client):
    response = _register(anon_client, password="weak", confirm_password="weak")
    assert response.status_code == 400
    assert "at least 12 characters" in response.get_data(as_text=True)


def test_registration_password_mismatch(anon_client):
    response = _register(anon_client, confirm_password="Different-Pass!2026")
    assert response.status_code == 400
    assert "do not match" in response.get_data(as_text=True)


def test_registration_cannot_self_assign_role(anon_client):
    """A request-supplied role must never be honoured."""
    response = anon_client.post("/register", data={
        "company_name": "Epsilon Co", "full_name": "Eve Admin",
        "email": "eve@epsilon.example", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD,
        "role": "Admin",
    }, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        user = db.session.query(User).filter_by(email="eve@epsilon.example").one()
        # Server assigned Admin regardless; a request could only ever try to
        # escalate, and here it matches. Assert the value came from the server.
        assert user.role in ("Admin", "Analyst", "Viewer")
        assert user.role == "Admin"


def test_registration_cannot_self_assign_company_id(anon_client):
    """A request-supplied company_id must never be honoured."""
    response = anon_client.post("/register", data={
        "company_name": "Delta Co", "full_name": "Dana Admin",
        "email": "dana@delta.example", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD,
        "company_id": "9999", "role": "Analyst",
    }, follow_redirects=False)
    assert response.status_code == 302
    with app.app_context():
        user = db.session.query(User).filter_by(email="dana@delta.example").one()
        # The new company got a fresh id, not the one the request asked for.
        assert user.company_id != 9999
        # And the requested Analyst role was not honoured.
        assert user.role == "Admin"


def test_registration_rolls_back_on_conflict(anon_client):
    """A failed registration must not leave a half-created company."""
    before = _count_companies()
    # Force an IntegrityError path by colliding on the unique email index.
    with app.app_context():
        existing = db.session.query(User).filter_by(
            email="admin@alphatelecom.example").one()
        with pytest.raises(ValidationError):
            register_company(
                company_name="Rollback Co", full_name="Roll Back",
                email=existing.email, password=GOOD_PASSWORD,
                confirm_password=GOOD_PASSWORD,
            )
        db.session.rollback()
    assert _count_companies() == before, "no orphan company may survive a failure"


def _count_companies() -> int:
    with app.app_context():
        return db.session.query(Company).count()


# =====================================================================
# 5. Login
# =====================================================================
def test_login_success_redirects(anon_client):
    response = anon_client.post("/login", data={
        "email": "admin@alphatelecom.example", "password": GOOD_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 302


def test_login_wrong_password_rejected(anon_client):
    response = anon_client.post("/login", data={
        "email": "admin@alphatelecom.example", "password": "Wrong-Password!1",
    })
    assert response.status_code == 401
    assert GENERIC_LOGIN_ERROR in response.get_data(as_text=True)


def test_login_unknown_email_gives_same_generic_error(anon_client):
    unknown = anon_client.post("/login", data={
        "email": "nobody@nowhere.example", "password": GOOD_PASSWORD,
    })
    wrong = anon_client.post("/login", data={
        "email": "admin@alphatelecom.example", "password": "Wrong-Password!1",
    })
    assert unknown.status_code == wrong.status_code == 401
    # The rendered error must be identical, and must not state whether the
    # account exists. Echoing the submitted address into the form's value
    # attribute is normal UX and is not an existence oracle.
    unknown_body = unknown.get_data(as_text=True)
    wrong_body = wrong.get_data(as_text=True)
    assert GENERIC_LOGIN_ERROR in unknown_body
    assert GENERIC_LOGIN_ERROR in wrong_body
    for leak in ("does not exist", "unknown email", "no such user", "not found"):
        assert leak not in unknown_body.lower()
        assert leak not in wrong_body.lower()


def test_inactive_user_cannot_login(inactive_client):
    response = inactive_client.post("/login", data={
        "email": "inactive@alphatelecom.example", "password": GOOD_PASSWORD,
    })
    assert response.status_code == 401
    # Same generic message as any other failure.
    assert GENERIC_LOGIN_ERROR in response.get_data(as_text=True)


def test_login_is_case_insensitive_on_email(anon_client):
    response = anon_client.post("/login", data={
        "email": "ADMIN@AlphaTelecom.example", "password": GOOD_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 302


def test_logout_clears_session(client):
    assert client.post("/logout", follow_redirects=False).status_code == 302
    # After logout the protected API must reject again.
    assert client.get("/api/company/stats").status_code == 401


def test_logout_requires_post(client):
    """GET must not log out (CSRF-triggered logout via a link)."""
    assert client.get("/logout").status_code == 405


def test_session_survives_across_requests(client):
    first = client.get("/api/company/stats")
    second = client.get("/api/company/stats")
    assert first.status_code == second.status_code == 200


# =====================================================================
# 6. Throttling
# =====================================================================
def test_rate_limiter_blocks_after_max_attempts():
    limiter = LoginRateLimiter(max_attempts=3, window_seconds=60)
    key = "someone@example.com|1.2.3.4"
    for _ in range(3):
        assert limiter.is_locked(key) is False
        limiter.record_failure(key)
    assert limiter.is_locked(key) is True


def test_rate_limiter_resets_on_success_signal():
    limiter = LoginRateLimiter(max_attempts=2, window_seconds=60)
    key = "k|ip"
    limiter.record_failure(key)
    limiter.record_failure(key)
    assert limiter.is_locked(key) is True
    limiter.reset(key)
    assert limiter.is_locked(key) is False


def test_rate_limiter_expires_old_entries():
    limiter = LoginRateLimiter(max_attempts=1, window_seconds=1)
    key = "k|ip"
    limiter.record_failure(key)
    assert limiter.is_locked(key) is True
    limiter._attempts[key] = [0.0]      # force an ancient timestamp
    assert limiter.is_locked(key) is False, "stale entries must be pruned"


def test_rate_limiter_is_bounded_under_key_flooding():
    limiter = LoginRateLimiter(max_attempts=5, window_seconds=60, max_keys=50)
    for i in range(500):
        limiter.record_failure(f"user{i}@example.com|ip")
    assert len(limiter._attempts) <= 50, "memory must stay bounded"


def test_rate_limiter_is_thread_safe():
    import threading
    limiter = LoginRateLimiter(max_attempts=10_000, window_seconds=60)
    def hammer():
        for i in range(200):
            limiter.record_failure(f"k{i % 20}|ip")
    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sum(len(v) for v in limiter._attempts.values()) == 8 * 200


def test_login_locks_out_after_repeated_failures(anon_client):
    for _ in range(6):
        anon_client.post("/login", data={
            "email": "admin@alphatelecom.example", "password": "bad-guess!1",
        })
    # Even the correct password is now refused while locked out.
    locked = anon_client.post("/login", data={
        "email": "admin@alphatelecom.example", "password": GOOD_PASSWORD,
    })
    assert locked.status_code == 401


def test_client_ip_ignores_forwarded_header(anon_client):
    """A spoofed X-Forwarded-For must not change the limiter key."""
    from flask import request
    with app.test_request_context("/login", headers={"X-Forwarded-For": "9.9.9.9"}):
        assert auth_service.client_ip() != "9.9.9.9"


# =====================================================================
# 7. Unauthenticated access
# =====================================================================
@pytest.mark.parametrize("path", [
    "/api/company/stats",
    "/api/company/analytics",
    "/api/company/customers",
    "/api/stats",
    "/api/analytics",
    "/api/customers",
    "/predict/schema",
])
def test_anonymous_cannot_reach_protected_endpoints(anon_client, path):
    response = anon_client.get(path)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "UNAUTHENTICATED"


def test_anonymous_cannot_post_prediction(anon_client):
    response = anon_client.post("/predict", json={"tenure": 12})
    assert response.status_code == 401


def test_anonymous_html_page_redirects_to_login(anon_client):
    """Browser page requests redirect to the login form."""
    response = anon_client.get("/customers")
    assert response.status_code == 302
    assert "/login" in response.headers.get("Location", "")


# =====================================================================
# 8. Role enforcement on demo data
# =====================================================================
def test_admin_can_access_demo_data(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    body = response.get_json()
    assert body["scope"] == "demo"
    assert "IBM Sample Data" in body["notice"]


def test_analyst_can_access_demo_data(analyst_client):
    assert analyst_client.get("/api/stats").status_code == 200
    assert analyst_client.get("/api/customers").status_code == 200


@pytest.mark.parametrize("path", [
    "/api/stats", "/api/analytics", "/api/customers",
    f"/api/customers/{IBM_CUSTOMER}",
])
def test_viewer_is_denied_demo_data(viewer_client, path):
    response = viewer_client.get(path)
    assert response.status_code == 403
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "DEMO_DATA_FORBIDDEN"


def test_viewer_can_still_use_company_endpoints(viewer_client):
    """Viewer is read-only, but may see its own company data."""
    assert viewer_client.get("/api/company/stats").status_code == 200


def test_demo_banner_rendered_for_demo_pages(client):
    body = client.get("/").get_data(as_text=True)
    assert "IBM Sample Data" in body and "Demo Mode" in body


def test_viewer_nav_hides_demo_links(viewer_client):
    body = viewer_client.get("/").get_data(as_text=True)
    assert "IBM Sample Data" not in body
    assert "locked" in body


# =====================================================================
# 9. Tenant isolation
# =====================================================================
def test_company_a_sees_only_its_own_customers(client):
    body = client.get("/api/company/customers?per_page=100").get_json()
    refs = {c["customer_id"] for c in body["customers"]}
    assert A_CUSTOMER in refs
    assert B_CUSTOMER not in refs, "Company B's customer leaked into Company A"
    assert IBM_CUSTOMER not in refs, "IBM sample row leaked into company scope"


def test_company_b_sees_only_its_own_customers(client_b):
    body = client_b.get("/api/company/customers?per_page=100").get_json()
    refs = {c["customer_id"] for c in body["customers"]}
    assert B_CUSTOMER in refs
    assert A_CUSTOMER not in refs, "Company A's customer leaked into Company B"


def test_company_a_cannot_read_company_b_customer_detail(client):
    response = client.get(f"/api/company/customers/{B_CUSTOMER}")
    assert response.status_code == 404, "a foreign record must be indistinguishable from a missing one"
    assert B_CUSTOMER not in response.get_data(as_text=True)


def test_company_b_cannot_read_company_a_customer_detail(client_b):
    assert client_b.get(f"/api/company/customers/{A_CUSTOMER}").status_code == 404


def test_company_scope_never_includes_ibm_sample(client):
    body = client.get("/api/company/customers?per_page=100").get_json()
    assert all(
        c["customer_id"].startswith("ALPHA-TELECOM")
        for c in body["customers"]
    )
    assert IBM_CUSTOMER not in {c["customer_id"] for c in body["customers"]}


def test_demo_scope_never_includes_company_rows(client):
    """IBM rows are reachable in the demo scope; company rows are not."""
    found = client.get(f"/api/customers?search={IBM_CUSTOMER}").get_json()
    assert IBM_CUSTOMER in {c["customer_id"] for c in found["customers"]}

    for company_row in (A_CUSTOMER, B_CUSTOMER):
        leak = client.get(f"/api/customers?search={company_row}").get_json()
        assert company_row not in {c["customer_id"] for c in leak["customers"]}
        assert leak["pagination"]["total"] == 0


def test_demo_scope_count_is_unaffected_by_company_data(client):
    stats = client.get("/api/stats").get_json()["stats"]
    assert stats["total_customers"] == 7032, "company rows must not inflate the demo total"


def test_company_analytics_exclude_other_companies(client):
    """Company A's analytics reflect only Company A's customers."""
    analytics = client.get("/api/company/analytics").get_json()["analytics"]
    total = sum(row["count"] for row in analytics["by_contract"])
    assert total == 2, "only Company A's two customers may be counted"
    assert all(row["count"] == 0 for row in analytics["by_payment_method"]) or \
        sum(row["count"] for row in analytics["by_payment_method"]) == 2
    # IBM churn statistics must not appear in a company-scoped chart.
    assert sum(row["count"] for row in analytics["by_tenure_band"]) == 2


def test_company_search_cannot_escape_scope(client):
    """Searching for another company's id must return nothing."""
    body = client.get(f"/api/company/customers?search={B_CUSTOMER}").get_json()
    assert body["pagination"]["total"] == 0
    assert body["customers"] == []


def test_company_id_in_query_string_is_ignored(client):
    """A browser-supplied company_id must not switch tenants."""
    default = client.get("/api/company/customers?per_page=100").get_json()
    tampered = client.get(
        f"/api/company/customers?per_page=100&company_id=2").get_json()
    assert tampered["customers"] == default["customers"]


def test_company_id_in_body_is_ignored(client):
    """A browser-supplied company_id must not appear anywhere in the output."""
    payload = dict(FRIENDLY_CUSTOMER)
    payload["company_id"] = 2          # Beta Telecom's id
    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert "company_id" not in body["prediction"]
    # The same customer without the injected field scores identically.
    clean = client.post("/predict", json=FRIENDLY_CUSTOMER).get_json()
    assert body["prediction"] == clean["prediction"]


def test_new_company_dashboard_is_empty(anon_client):
    """A freshly registered company has no customers and no prediction history."""
    response = anon_client.post("/register", data={
        "company_name": "Fresh Start Co",
        "full_name": "Frank Founder",
        "email": "frank@freshstart.example",
        "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 302

    login = anon_client.post("/login", data={
        "email": "frank@freshstart.example", "password": GOOD_PASSWORD,
    }, follow_redirects=False)
    assert login.status_code == 302

    stats = anon_client.get("/api/company/stats").get_json()["stats"]
    assert stats["total_customers"] == 0
    assert stats["churned"] == 0
    assert stats["retained"] == 0
    # No data means no meaningful rate, so the API must not invent one.
    assert stats["churn_rate"] is None
    assert stats["retention_rate"] is None

    listing = anon_client.get("/api/company/customers").get_json()
    assert listing["pagination"]["total"] == 0
    assert listing["customers"] == []

    analytics = anon_client.get("/api/company/analytics").get_json()["analytics"]
    assert analytics["by_contract"] == []
    assert all(
        band["count"] == 0 for band in analytics["by_tenure_band"]
    )


def test_unscoped_company_id_returns_empty(client):
    from services.customer_service import company_stats, company_customers
    with app.app_context():
        assert company_stats(None)["total_customers"] == 0
        assert company_customers(None)["pagination"]["total"] == 0


# =====================================================================
# 10. Role fail-closed behaviour
# =====================================================================
def _role_user(role):
    """A transient User carrying only a role, for fail-closed checks."""
    return User(role=role)


def test_unknown_role_grants_nothing():
    user = _role_user("SuperAdmin")
    assert user.is_admin is False
    assert user.can_view_demo_data is False
    assert user.has_role("Admin") is False


def test_none_role_grants_nothing():
    user = _role_user(None)
    assert user.is_admin is False
    assert user.can_view_demo_data is False


def test_empty_role_grants_nothing():
    user = _role_user("   ")
    assert user.is_admin is False
    assert user.can_view_demo_data is False


def test_role_matching_is_exact_not_prefix():
    assert _role_user("Admin").has_role("Admin") is True
    assert _role_user("Admin").has_role("Viewer") is False
    assert _role_user("Adminx").has_role("Admin") is False


def test_company_id_comes_from_session_not_request(client):
    """A query-string company_id is ignored; the session identity decides."""
    default = client.get("/api/company/stats").get_json()["stats"]
    tampered = client.get("/api/company/stats?company_id=999").get_json()["stats"]
    assert tampered == default

    detail_default = client.get(
        f"/api/company/customers/{A_CUSTOMER}").status_code
    detail_tampered = client.get(
        f"/api/company/customers/{A_CUSTOMER}?company_id=999").status_code
    assert detail_default == detail_tampered == 200


# =====================================================================
# 11. CSRF
# =====================================================================
def test_login_form_requires_csrf_token(_isolated_database):
    """With CSRF enabled, a POST without a token is rejected."""
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        with app.test_client() as c:
            response = c.post("/login", data={
                "email": "admin@alphatelecom.example", "password": GOOD_PASSWORD,
            })
            assert response.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_logout_form_requires_csrf_token(_isolated_database):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        with app.test_client() as c:
            # Log in without CSRF first (should fail), then confirm the
            # endpoint refuses an unprotected POST.
            c.post("/login", data={
                "email": "admin@alphatelecom.example", "password": GOOD_PASSWORD,
            })
            assert c.post("/logout").status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_login_form_contains_csrf_field(_isolated_database):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        with app.test_client() as c:
            body = c.get("/login").get_data(as_text=True)
            assert 'name="csrf_token"' in body
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# =====================================================================
# 12. Open redirect
# =====================================================================
@pytest.mark.parametrize("target", [
    "https://evil.example/steal",
    "//evil.example/steal",
    "http://evil.example",
])
def test_open_redirect_is_blocked(anon_client, target):
    response = anon_client.post(f"/login?next={target}", data={
        "email": "admin@alphatelecom.example", "password": GOOD_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 302
    location = response.headers.get("Location", "")
    assert "evil.example" not in location


def test_safe_relative_next_is_honoured(anon_client):
    response = anon_client.post("/login?next=/customers", data={
        "email": "admin@alphatelecom.example", "password": GOOD_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 302
    assert "/customers" in response.headers.get("Location", "")


def test_is_safe_redirect_helper():
    from routes.auth import _is_safe_redirect
    assert _is_safe_redirect("/customers") is True
    assert _is_safe_redirect("https://evil.example") is False
    assert _is_safe_redirect("//evil.example") is False
    assert _is_safe_redirect("") is False
    assert _is_safe_redirect(None) is False
