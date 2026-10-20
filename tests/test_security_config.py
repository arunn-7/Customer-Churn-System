"""Tests for the security configuration review and app hardening.

    .\\venv\\Scripts\\python.exe -m pytest tests\\test_security_config.py -q

These are pure unit tests: they never connect to a database and never touch
ml/model.pkl. They assert with real ``assert`` statements so a false condition
fails the test.
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from security.config_review import (  # noqa: E402
    MIN_SECRET_KEY_LENGTH,
    assert_production_readiness,
    critical_findings,
    generate_secret_key,
    log_findings,
    review_all,
    review_cookies,
    review_debug_mode,
    review_secret_key,
)
from config import Config, _env_bool  # noqa: E402


# ---------------------------------------------------------------------------
# SECRET_KEY strength
# ---------------------------------------------------------------------------
def test_missing_secret_key_is_critical():
    findings = review_secret_key(None)
    assert any(f.code == "SECRET_KEY_MISSING" for f in findings)
    assert any(f.severity == "critical" for f in findings)


def test_empty_secret_key_is_critical():
    findings = review_secret_key("")
    assert any(f.code == "SECRET_KEY_MISSING" for f in findings)


def test_short_secret_key_is_critical():
    findings = review_secret_key("short-key")
    assert any(f.code == "SECRET_KEY_TOO_SHORT" for f in findings)
    assert any(f.severity == "critical" for f in findings)


def test_long_random_secret_key_passes():
    findings = review_secret_key(generate_secret_key())
    assert findings == [], f"expected no findings, got {[str(f) for f in findings]}"


def test_well_known_secret_key_is_critical():
    for bad in ("secret", "changeme", "dev", "password"):
        findings = review_secret_key(bad * 12)
        codes = {f.code for f in findings}
        assert "SECRET_KEY_WELL_KNOWN" in codes, f"{bad!r} not flagged"


def test_low_entropy_secret_key_warns():
    findings = review_secret_key("secret_key_secret_key")
    assert any(f.code == "SECRET_KEY_LOW_ENTROPY" for f in findings)


def test_secret_key_review_never_leaks_the_value():
    secret = "my_very_secret_value_abc123xyz"
    findings = review_secret_key(secret)
    blob = " ".join(str(f) for f in findings)
    assert secret not in blob, "finding text must not echo the secret"
    # Only the length is reported, never the content.
    assert str(len(secret)) in blob or len(secret) >= MIN_SECRET_KEY_LENGTH


# ---------------------------------------------------------------------------
# Cookie transport security
# ---------------------------------------------------------------------------
def test_insecure_cookies_critical_outside_debug():
    findings = review_cookies(secure=False, is_debug=False)
    assert any(f.code == "COOKIE_SECURE_DISABLED" and f.severity == "critical"
               for f in findings)


def test_insecure_cookies_only_info_in_debug():
    findings = review_cookies(secure=False, is_debug=True)
    assert any(f.code == "COOKIE_SECURE_DISABLED" and f.severity == "info"
               for f in findings)
    assert critical_findings(findings) == []


def test_secure_cookies_produce_no_finding():
    assert review_cookies(secure=True, is_debug=False) == []


# ---------------------------------------------------------------------------
# Debug mode
# ---------------------------------------------------------------------------
def test_debug_mode_warns():
    findings = review_debug_mode(True)
    assert findings and findings[0].code == "DEBUG_ENABLED"
    assert findings[0].severity == "warning"


def test_production_mode_has_no_debug_finding():
    assert review_debug_mode(False) == []


# ---------------------------------------------------------------------------
# Production readiness gate
# ---------------------------------------------------------------------------
def test_production_gate_blocks_on_critical_findings():
    findings = review_secret_key("short")
    with pytest.raises(RuntimeError) as excinfo:
        assert_production_readiness(findings, enabled=True)
    assert "unsafe production configuration" in str(excinfo.value)


def test_production_gate_passes_when_disabled():
    # Disabled by default so local development is never blocked.
    findings = review_secret_key("short")
    assert_production_readiness(findings, enabled=False)   # must not raise


def test_production_gate_passes_when_clean():
    findings = review_secret_key(generate_secret_key())
    assert_production_readiness(findings, enabled=True)    # must not raise


def test_critical_filtering():
    findings = review_secret_key("short") + review_debug_mode(True)
    assert all(f.severity == "critical" for f in critical_findings(findings))
    assert len(critical_findings(findings)) >= 1


def test_generated_key_is_strong_and_unique():
    a, b = generate_secret_key(), generate_secret_key()
    assert a != b
    assert len(a) >= MIN_SECRET_KEY_LENGTH


def test_log_findings_never_raises_on_varied_input(caplog):
    findings = review_secret_key(None) + review_debug_mode(True)
    log_findings(findings)      # must not raise


# ---------------------------------------------------------------------------
# Config surface
# ---------------------------------------------------------------------------
def test_cookie_hardening_defaults_are_set():
    assert Config.SESSION_COOKIE_HTTPONLY is True
    assert Config.SESSION_COOKIE_SAMESITE == "Lax"
    assert Config.REMEMBER_COOKIE_HTTPONLY is True
    assert Config.REMEMBER_COOKIE_SAMESITE == "Lax"


def test_secure_cookie_defaults_off_for_local_http():
    # Enabling Secure by default would break plain-HTTP local development.
    assert Config.SESSION_COOKIE_SECURE is False


def test_csrf_is_enabled_with_expiry():
    assert Config.WTF_CSRF_ENABLED is True
    assert Config.WTF_CSRF_TIME_LIMIT == 3600


def test_json_api_endpoints_are_csrf_exempt():
    # These accept fetch()/JSON, not browser forms.
    #
    # Names must be FULLY QUALIFIED: Flask registers blueprint routes with the
    # blueprint name as a prefix, so `predict_bp`'s view is "predict.predict",
    # not "predict". This test previously asserted the short names, which
    # silently registered no exemption at all and broke the prediction form.
    exempt = Config.CSRF_EXEMPT_ENDPOINTS
    assert "predict.predict" in exempt
    assert "predict.predict_explain" in exempt
    assert "dashboard.api_stats" in exempt
    # Auth forms must NOT be exempt, under any naming.
    assert not any(name.endswith(".login") for name in exempt)
    assert not any(name.endswith(".logout") for name in exempt)
    assert not any("register" in name for name in exempt)


def test_session_lifetimes_are_bounded():
    assert Config.PERMANENT_SESSION_LIFETIME <= 60 * 60 * 24
    assert Config.REMEMBER_COOKIE_DURATION <= 60 * 60 * 24 * 30


def test_env_bool_parsing(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on", "On"):
        monkeypatch.setenv("__T_FLAG__", value)
        assert _env_bool("__T_FLAG__") is True
    for value in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv("__T_FLAG__", value)
        assert _env_bool("__T_FLAG__") is False
    monkeypatch.delenv("__T_FLAG__", raising=False)
    assert _env_bool("__T_FLAG__", default=True) is True


def test_review_all_aggregates(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "tiny")
    findings = review_all(
        {"SECRET_KEY": "tiny", "SESSION_COOKIE_SECURE": False},
        is_debug=False, host="localhost",
    )
    codes = {f.code for f in findings}
    assert "SECRET_KEY_TOO_SHORT" in codes
    assert "COOKIE_SECURE_DISABLED" in codes


# ---------------------------------------------------------------------------
# Isolation protections still intact
# ---------------------------------------------------------------------------
def test_conftest_fail_closed_protections_present():
    """The isolated test database guards must remain in place."""
    conftest = os.path.join(PROJECT_ROOT, "tests", "conftest.py")
    source = open(conftest, encoding="utf-8").read()
    assert "Refusing to run tests" in source
    assert "_assert_test_engine" in source
    assert 'TEST_DB_NAME' in source


def test_production_db_name_never_hardcoded_in_conftest():
    """conftest must read the production name from .env, never hardcode it."""
    conftest = os.path.join(PROJECT_ROOT, "tests", "conftest.py")
    source = open(conftest, encoding="utf-8").read()
    assert 'DB_NAME"]' in source          # read from environment
    assert '"customer_churn_db"' not in source
