"""Security configuration review.

Runs at start-up and reports configuration weaknesses without ever printing a
secret value. Nothing here changes behaviour on its own beyond logging; the one
exception is :func:`assert_production_readiness`, which refuses to start a
deployment in "production" mode with an unsafe configuration.

This module exists so that hardening mistakes surface during development
instead of during a security incident.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Flask signs session cookies with SECRET_KEY. Anything short of this is not
# realistically unguessable.
MIN_SECRET_KEY_LENGTH = 32

# Values that must never reach production.
WEAK_SECRET_MARKERS = frozenset({
    "secret", "changeme", "change-me", "dev", "development", "key",
    "secret_key", "supersecret", "password", "test", "flask",
})

INSECURE_DEFAULTS = frozenset({
    "dev", "development", "secret", "changeme", "change-me", "key",
    "secret-key", "password", "test", "testing", "local",
})


@dataclass(frozen=True)
class Finding:
    severity: str      # "info" | "warning" | "critical"
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"[{self.severity.upper():8}] {self.code}: {self.message}"


def review_secret_key(secret: str | None) -> list[Finding]:
    """Assess SECRET_KEY strength without revealing it."""
    findings: list[Finding] = []
    if not secret:
        return [Finding(
            "critical", "SECRET_KEY_MISSING",
            "SECRET_KEY is not set. Sessions cannot be signed.",
        )]

    if len(secret) < MIN_SECRET_KEY_LENGTH:
        findings.append(Finding(
            "critical", "SECRET_KEY_TOO_SHORT",
            f"SECRET_KEY is {len(secret)} characters; at least "
            f"{MIN_SECRET_KEY_LENGTH} are required for session signing.",
        ))

    lowered = secret.strip().lower()
    if lowered in WEAK_SECRET_MARKERS:
        findings.append(Finding(
            "critical", "SECRET_KEY_WELL_KNOWN",
            "SECRET_KEY matches a well-known placeholder value. "
            "Rotate it immediately.",
        ))
    else:
        # Catch padding such as "secretsecretsecret..." -- repeated or
        # concatenated weak words are just as guessable as the bare word.
        for marker in WEAK_SECRET_MARKERS:
            if len(marker) >= 3 and len(lowered) % len(marker) == 0:
                unit = lowered[:len(marker)]
                if lowered == unit * (len(lowered) // len(marker)):
                    findings.append(Finding(
                        "critical", "SECRET_KEY_WELL_KNOWN",
                        "SECRET_KEY is a repetition of a well-known "
                        "placeholder value. Rotate it immediately.",
                    ))
                    break

    # Underscore-vs-dash typosquatting of "secret_key" are common.
    if set(secret.strip().lower()) <= set("abcdefghijklmnopqrstuvwxyz_"):
        findings.append(Finding(
            "warning", "SECRET_KEY_LOW_ENTROPY",
            "SECRET_KEY uses only lowercase letters and underscores, which "
            "suggests a hand-written placeholder rather than random bytes.",
        ))

    return findings


def review_cookies(secure: bool, is_debug: bool) -> list[Finding]:
    """Assess session/remember cookie transport security."""
    findings: list[Finding] = []
    if not secure:
        if is_debug:
            findings.append(Finding(
                "info", "COOKIE_SECURE_DISABLED",
                "Session cookies are not Secure because debug mode is on. "
                "This is expected for local HTTP development.",
            ))
        else:
            findings.append(Finding(
                "critical", "COOKIE_SECURE_DISABLED",
                "Session and remember-me cookies are not marked Secure while "
                "not in debug mode. Set COOKIE_SECURE=true behind HTTPS.",
            ))
    return findings


def review_debug_mode(debug: bool) -> list[Finding]:
    if debug:
        return [Finding(
            "warning", "DEBUG_ENABLED",
            "Flask debug mode exposes an interactive console and is unsafe "
            "for any deployment.",
        )]
    return []


def review_insecure_hosts(app_name: str, host: str) -> list[Finding]:
    if host.strip().lower() in INSECURE_DEFAULTS:
        return [Finding(
            "warning", "INSECURE_HOSTNAME",
            f"Application host {host!r} is a placeholder; use a real hostname.",
        )]
    return []


def review_all(config: dict, *, is_debug: bool, host: str) -> list[Finding]:
    findings: list[Finding] = []
    findings += review_secret_key(config.get("SECRET_KEY"))
    findings += review_cookies(bool(config.get("SESSION_COOKIE_SECURE")), is_debug)
    findings += review_debug_mode(is_debug)
    findings += review_insecure_hosts(config.get("ENV", "app"), host)
    return findings


def log_findings(findings: list[Finding]) -> None:
    for finding in findings:
        if finding.severity == "critical":
            logger.critical("%s", finding)
        elif finding.severity == "warning":
            logger.warning("%s", finding)
        else:
            logger.info("%s", finding)


def critical_findings(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "critical"]


def assert_production_readiness(findings: list[Finding], *, enabled: bool) -> None:
    """Refuse to start a 'production' deployment with critical findings.

    Disabled by default so local development is never blocked. Enable with
    ``ENFORCE_PRODUCTION_CONFIG=true``.
    """
    if not enabled:
        return
    critical = critical_findings(findings)
    if critical:
        joined = "\n  - ".join(f"{f.code}: {f.message}" for f in critical)
        raise RuntimeError(
            "Refusing to start: unsafe production configuration.\n  - " + joined
        )


def generate_secret_key() -> str:
    """Produce a strong key for the documented rotation procedure.

    Never call this at start-up -- a randomly generated key would invalidate
    every existing session on each restart. It exists so an operator can run it
    locally and copy the output into .env. The value is never logged.
    """
    return secrets.token_urlsafe(48)
