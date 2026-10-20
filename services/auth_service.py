"""Registration, login helpers and login throttling.

Security properties
-------------------
* Emails are trimmed, syntax-checked with `email_validator`, then lowercased
  before any lookup or insert. `email_validator` preserves the local-part case
  (`USER@x.com` stays uppercase), which would otherwise let two accounts differ
  only by case, so the lowercasing here is what makes the unique index effective.
* Registration creates the company and its first administrator in a single
  transaction. Any failure rolls the whole thing back, so a company is never
  left without an owner or an administrator without a company.
* Role is assigned server-side. Nothing in the request can promote a registrant
  to Admin, and no company_id from the request is ever trusted.
* Login failures return one generic message for unknown email, wrong password
  and disabled account, so the endpoint is not an account-existence oracle.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.db import db
from models.company import Company
from models.user import ROLE_ADMIN, User

# ----------------------------------------------------------------------
# Validation constants
# ----------------------------------------------------------------------
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128          # bcrypt truncates past 72 bytes; reject early
SLUG_MAX_LENGTH = 64

# Deliberately generic: the same text for every authentication failure.
GENERIC_LOGIN_ERROR = "Invalid email or password."


class ValidationError(Exception):
    """Raised with per-field messages safe to render on a form."""

    def __init__(self, errors: dict[str, str]) -> None:
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


# ----------------------------------------------------------------------
# Email normalisation
# ----------------------------------------------------------------------
def normalize_email(raw: str | None) -> str:
    """Trim, validate and lowercase an email address.

    Raises ValidationError with a field-level message on bad syntax.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise ValidationError({"email": "Email address is required."})
    try:
        validate_email(candidate, check_deliverability=False)
    except EmailNotValidError as exc:
        # EmailSyntaxError has no .reason; str() is always safe.
        raise ValidationError({"email": "Enter a valid email address."}) from exc
    # Lowercase the whole address, not just the domain.
    return candidate.lower()


def find_user_by_email(email: str | None) -> User | None:
    """Look up by already-normalised email."""
    normalized = normalize_email(email)
    return db.session.execute(
        select(User).where(User.email == normalized)
    ).scalar_one_or_none()


# ----------------------------------------------------------------------
# Password policy
# ----------------------------------------------------------------------
def validate_password(password: str | None) -> None:
    """Reject weak passwords. Returns None; raises ValidationError otherwise."""
    errors: dict[str, str] = {}
    value = password or ""

    if not value:
        raise ValidationError({"password": "Password is required."})
    if len(value) < MIN_PASSWORD_LENGTH:
        errors["password"] = (
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    elif len(value) > MAX_PASSWORD_LENGTH:
        errors["password"] = (
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        )
    else:
        if not re.search(r"[a-z]", value):
            errors["password"] = "Password must include a lowercase letter."
        elif not re.search(r"[A-Z]", value):
            errors["password"] = "Password must include an uppercase letter."
        elif not re.search(r"\d", value):
            errors["password"] = "Password must include a digit."
        elif not re.search(r"[^A-Za-z0-9]", value):
            errors["password"] = "Password must include a symbol."

    if errors:
        raise ValidationError(errors)


# ----------------------------------------------------------------------
# Slug generation
# ----------------------------------------------------------------------
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """ASCII, lowercase, hyphen-separated slug from a company name."""
    normalized = unicodedata.normalize("NFKD", name or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_STRIP.sub("-", ascii_only.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH] or "company"


def _unique_slug(name: str) -> str:
    """Append a random suffix until the unique index is satisfied."""
    base = slugify(name)
    for _ in range(10):
        candidate = f"{base}-{secrets.token_hex(3)}"
        exists = db.session.execute(
            select(Company.id).where(Company.slug == candidate)
        ).first()
        if not exists:
            return candidate
    # Practically unreachable; uniqueness is still enforced by the index.
    return f"{base}-{secrets.token_hex(8)}"


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------
def register_company(
    *,
    company_name: str,
    full_name: str,
    email: str,
    password: str,
    confirm_password: str,
) -> tuple[Company, User]:
    """Create a company and its first administrator atomically.

    The role is hardcoded to Admin and company_id always comes from the newly
    created Company. Nothing caller-supplied influences either.
    """
    errors: dict[str, str] = {}

    company_name = (company_name or "").strip()
    if not company_name:
        errors["company_name"] = "Company name is required."
    elif len(company_name) > 150:
        errors["company_name"] = "Company name must be at most 150 characters."

    full_name = (full_name or "").strip()
    if not full_name:
        errors["full_name"] = "Your full name is required."
    elif len(full_name) > 100:
        errors["full_name"] = "Name must be at most 100 characters."

    try:
        normalized_email = normalize_email(email)
    except ValidationError as exc:
        errors.update(exc.errors)
        normalized_email = ""

    try:
        validate_password(password)
    except ValidationError as exc:
        errors.update(exc.errors)

    if password and confirm_password and password != confirm_password:
        errors["confirm_password"] = "Passwords do not match."

    if errors:
        raise ValidationError(errors)

    # Duplicate check is advisory; the unique index is authoritative.
    if find_user_by_email(normalized_email) is not None:
        raise ValidationError(
            {"email": "An account with that email address already exists."}
        )

    try:
        company = Company(name=company_name, slug=_unique_slug(company_name), is_active=True)
        db.session.add(company)
        db.session.flush()   # assigns company.id without committing

        user = User(
            full_name=full_name,
            email=normalized_email,
            role=ROLE_ADMIN,          # server-assigned; never from the request
            company_id=company.id,    # server-assigned; never from the request
            is_active_flag=True,
        )
        user.set_password(password)
        db.session.add(user)

        db.session.commit()
        return company, user

    except IntegrityError as exc:
        # Concurrent registration with the same email/slug: roll everything
        # back and report a generic message rather than leaking the constraint.
        db.session.rollback()
        raise ValidationError(
            {"email": "An account with that email address already exists."}
        ) from exc
    except Exception:
        db.session.rollback()
        raise


# ----------------------------------------------------------------------
# Login throttling
# ----------------------------------------------------------------------
@dataclass
class _Attempt:
    timestamps: list[float] = field(default_factory=list)


class LoginRateLimiter:
    """Bounded, thread-safe sliding-window limiter keyed by email + client IP.

    LIMITATION (documented deliberately): this state is per-process and resets
    on restart, so it does NOT protect a multi-worker or multi-instance
    deployment. Those need a shared store (Redis, or a database table), which
    would require a migration and is out of scope for this checkpoint.
    """

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300,
                 max_keys: int = 10_000) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        """Drop expired buckets and hard-bound the table size."""
        cutoff = now - self.window_seconds
        stale = [k for k, v in self._attempts.items()
                 if not v or v[-1] <= cutoff]
        for key in stale:
            self._attempts.pop(key, None)
        self._enforce_bound()

    def _enforce_bound(self) -> None:
        """Cap the number of tracked keys even under key flooding.

        Evicts the oldest-inserted keys. Runs after every insert so the bound
        holds immediately, not just on the next call.
        """
        overflow = len(self._attempts) - self.max_keys
        if overflow > 0:
            for key in list(self._attempts.keys())[:overflow]:
                self._attempts.pop(key, None)

    def is_locked(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            hits = self._attempts.get(key, [])
            recent = [t for t in hits if t > now - self.window_seconds]
            if recent:
                self._attempts[key] = recent
            return len(recent) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            hits = self._attempts.setdefault(key, [])
            hits.append(now)
            hits[:] = [t for t in hits if t > now - self.window_seconds]
            # Re-apply the bound: this insert may have pushed us over.
            self._enforce_bound()

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def clear(self) -> None:
        """Test helper."""
        with self._lock:
            self._attempts.clear()


# Process-wide limiter instance.
login_limiter = LoginRateLimiter()


def client_ip() -> str:
    """Best-effort client address.

    Deliberately does NOT read X-Forwarded-For / X-Real-IP: those are trivially
    spoofable unless a trusted proxy is configured, and trusting them would let
    an attacker bypass the limiter by forging the header.
    """
    from flask import request

    try:
        return request.remote_addr or "unknown"
    except RuntimeError:
        return "unknown"


def throttle_key(email: str | None) -> str:
    """Limiter key: normalised email plus client IP."""
    normalized = (email or "").strip().lower()[:255]
    return f"{normalized}|{client_ip()}"


def authenticate(email: str | None, password: str | None) -> User | None:
    """Verify credentials, returning None for every failure mode.

    Inactive users and locked-out clients are indistinguishable from a wrong
    password at the caller's level.
    """
    key = throttle_key(email)
    if login_limiter.is_locked(key):
        return None

    user = None
    try:
        user = find_user_by_email(email)
    except ValidationError:
        user = None

    if user is None:
        # Spend comparable time so a missing account is not detectably faster.
        login_limiter.record_failure(key)
        return None

    if not user.check_password(password or ""):
        login_limiter.record_failure(key)
        return None

    if not user.is_active:
        # Correct password but suspended account.
        login_limiter.record_failure(key)
        return None

    login_limiter.reset(key)
    return user
