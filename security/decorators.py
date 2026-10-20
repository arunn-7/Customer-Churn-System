"""Centralised authentication and authorization decorators.

Every protected route uses these, so authorization decisions live in one place
rather than being restated per view.

Content negotiation
-------------------
API clients get JSON envelopes; browsers get HTML pages. An unauthenticated
request therefore never receives a stack trace, and never receives HTML when it
asked for JSON.
"""

from __future__ import annotations

import functools
from typing import Callable

from flask import jsonify, render_template, request
from flask_login import current_user

from models.user import User

# Routes an anonymous visitor is allowed to reach.
PUBLIC_ENDPOINTS = frozenset({
    "login", "register_company", "static", "favicon",
})


def _wants_json() -> bool:
    """True when the caller is an API client rather than a browser."""
    if request.path.startswith("/api/") or request.path.startswith("/predict"):
        return True
    if request.is_json:
        return True
    accept = request.accept_mimetypes
    return accept["text/html"] < accept["application/json"]


def _deny(status: int, code: str, message: str):
    if _wants_json():
        return jsonify({"success": False, "error": {"code": code, "message": message}}), status
    return render_template("denied.html", active_page="", code=status, message=message), status


def login_required(view: Callable) -> Callable:
    """Require an authenticated, active user.

    Replaces Flask-Login's default so that API callers get a JSON 401 and
    browsers get the login page.
    """

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            if _wants_json():
                return jsonify({
                    "success": False,
                    "error": {"code": "UNAUTHENTICATED",
                              "message": "Authentication required."},
                }), 401
            return render_template("login.html", active_page="login",
                                   next=request.path), 401        # Flask-Login would already reject an inactive user, but being explicit
        # means a deactivated mid-session account loses access immediately.
        if not getattr(current_user, "is_active", False):
            return _deny(403, "ACCOUNT_INACTIVE", "This account is not active.")
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles: str):
    """Require one of the listed roles. Fails closed on an unknown role."""

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not current_user.has_role(*roles):
                return _deny(
                    403, "FORBIDDEN",
                    "Your role does not permit this action.",
                )
            return view(*args, **kwargs)

        return wrapped

    return decorator


def demo_access_required(view: Callable) -> Callable:
    """Restrict IBM sample/demo data to roles permitted to see it.

    Viewer is denied. This is the only thing that stops demo data reaching a
    read-only account.
    """

    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.can_view_demo_data:
            return _deny(
                403, "DEMO_DATA_FORBIDDEN",
                "IBM sample data is not available to Viewer accounts.",
            )
        return view(*args, **kwargs)

    return wrapped


def current_company_id() -> int | None:
    """The authenticated user's company id, from the server-side session only.

    Never reads a request parameter. Returns None when unauthenticated, which
    every company-scoped query treats as "match nothing".
    """
    if not current_user.is_authenticated:
        return None
    user: User = current_user
    return user.company_id_value


def company_required(view: Callable) -> Callable:
    """Require an authenticated user with a resolvable company."""

    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_company_id() is None:
            return _deny(403, "NO_COMPANY", "Your account is not linked to a company.")
        return view(*args, **kwargs)

    return wrapped
