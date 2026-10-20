"""Registration, login and logout.

Registration and login are HTML form endpoints protected by CSRF. Logout uses
POST so it cannot be triggered by a cross-site link or an image tag.
"""

from __future__ import annotations

from urllib.parse import urlparse

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from security.decorators import login_required as auth_login_required
from services.auth_service import (
    GENERIC_LOGIN_ERROR,
    ValidationError,
    authenticate,
    normalize_email,
    register_company,
)

auth_bp = Blueprint("auth", __name__)


def _is_safe_redirect(target: str | None) -> bool:
    """Reject absolute URLs, protocol-relative URLs and external hosts.

    Prevents open redirect after login. Only same-host, path-only targets are
    followed.
    """
    if not target:
        return False
    # "//evil.com" is protocol-relative and must be rejected.
    if target.startswith("//") or target.startswith("\\\\"):
        return False
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return False
    return target.startswith("/")


def _safe_next(default_endpoint: str) -> str:
    return url_for(default_endpoint)


@auth_bp.route("/register", methods=["GET", "POST"])
def register_company_view():
    """Create a company and its first administrator."""
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    form = {}
    errors: dict[str, str] = {}
    if request.method == "POST":
        form = {
            "company_name": request.form.get("company_name", "").strip(),
            "full_name": request.form.get("full_name", "").strip(),
            "email": request.form.get("email", "").strip(),
        }
        try:
            register_company(
                company_name=request.form.get("company_name", ""),
                full_name=request.form.get("full_name", ""),
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
                confirm_password=request.form.get("confirm_password", ""),
            )
        except ValidationError as exc:
            errors = exc.errors
        else:
            flash("Company created. Please sign in as its administrator.", "success")
            return redirect(url_for("auth.login"))

    return render_template(
        "register.html", active_page="register", form=form, errors=errors
    ), (400 if errors else 200)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate an existing user."""
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    form = {}
    error = None
    if request.method == "POST":
        email = request.form.get("email", "")
        form = {"email": email}
        try:
            user = authenticate(email, request.form.get("password", ""))
        except ValidationError:
            user = None

        if user is None:
            # One generic message for unknown email, wrong password, inactive
            # account and throttling. Never reveals which.
            error = GENERIC_LOGIN_ERROR
        else:
            login_user(user)
            target = request.args.get("next") or request.form.get("next")
            return redirect(target if _is_safe_redirect(target) else _safe_next("home"))

    return render_template(
        "login.html", active_page="login", form=form, error=error
    ), (401 if error else 200)


@auth_bp.route("/logout", methods=["POST"])
@auth_login_required
def logout():
    """Invalidate the session. POST-only to prevent CSRF-triggered logout."""
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))
