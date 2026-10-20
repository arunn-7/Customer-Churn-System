import os

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, login_required
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect, CSRFError

from config import Config
from database.db import db
from models.company import Company
from models.customer import Customer
from models.user import User
from routes.auth import auth_bp
from routes.company import company_bp
from routes.dashboard import dashboard_bp
from routes.predict import predict_bp
from security.config_review import assert_production_readiness, log_findings, review_all
from security.decorators import PUBLIC_ENDPOINTS
from security.passwords import bcrypt

app = Flask(__name__)

app.config.from_object(Config)

db.init_app(app)

# Schema migrations are owned by Alembic (Flask-Migrate). `flask db <cmd>`.
migrate = Migrate(app, db)

# ----------------------------------------------------------------------
# Security extensions
# ----------------------------------------------------------------------
bcrypt.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"


@login_manager.user_loader
def load_user(user_id: str):
    """Load the signed-in user for each request."""
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@login_manager.unauthorized_handler
def handle_unauthorized():
    """API callers get JSON; browsers are sent to the login page."""
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({
            "success": False,
            "error": {"code": "UNAUTHENTICATED", "message": "Authentication required."},
        }), 401
    return redirect(url_for("auth.login", next=request.path))


# CSRF protects browser form posts. The JSON APIs listed in
# Config.CSRF_EXEMPT_ENDPOINTS are exempt because they are called by fetch()
# with a JSON content type, not by an HTML form. Authentication endpoints are
# deliberately NOT exempt.
csrf = CSRFProtect(app)


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    """Return a readable message without exposing internals."""
    message = "Your session expired or the form was not submitted correctly. Please try again."
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({
            "success": False,
            "error": {"code": "CSRF_ERROR", "message": message},
        }), 400
    return render_template("denied.html", active_page="", code=400, message=message), 400


# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(company_bp)
app.register_blueprint(predict_bp)
app.register_blueprint(dashboard_bp)

# CSRF protects browser form posts. The JSON APIs named in
# Config.CSRF_EXEMPT_ENDPOINTS are exempt because they are called by fetch()
# with a JSON content type rather than submitted as an HTML form; they still
# require an authenticated session. Authentication endpoints are deliberately
# NOT exempt. Flask-WTF exempts view *functions*, so endpoint names are
# resolved through app.view_functions here, after blueprint registration.
#
# A name that does not resolve registers NO exemption and silently breaks the
# corresponding form at runtime, so an unresolved name is a hard error.
_unresolved: list[str] = []
for _endpoint in Config.CSRF_EXEMPT_ENDPOINTS:
    _view = app.view_functions.get(_endpoint)
    if _view is None:
        # Tolerate a missing blueprint prefix, but only when unambiguous.
        _candidates = [
            name for name in app.view_functions
            if name.rsplit(".", 1)[-1] == _endpoint.rsplit(".", 1)[-1]
        ]
        if len(_candidates) == 1:
            _view = app.view_functions[_candidates[0]]
        else:
            _unresolved.append(_endpoint)
            continue
    csrf.exempt(_view)

if _unresolved:
    raise RuntimeError(
        "Config.CSRF_EXEMPT_ENDPOINTS names endpoints that do not exist: "
        + ", ".join(_unresolved)
        + ". Registered endpoints: "
        + ", ".join(sorted(app.view_functions))
    )

# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------
@app.route("/")
@login_required
def home():
    """Dashboard is the landing page."""
    return render_template("dashboard.html", active_page="dashboard")


@app.route("/predict")
@login_required
def predict_page():
    """Customer churn prediction form."""
    return render_template("predict.html", active_page="predict")


@app.route("/customers")
@login_required
def customers_page():
    """Searchable customer directory."""
    return render_template("customers.html", active_page="customers")


@app.route("/test-db")
def test_db():
    try:
        db.engine.connect()
        return "Database Connected Successfully!"
    except Exception:
        # Do not leak the driver message to the browser.
        return "Database Connection Failed", 503


# ----------------------------------------------------------------------
# Error handlers
# ----------------------------------------------------------------------
def _wants_json():
    """True for API callers, False for a browser navigating to a page.

    API paths always get JSON. Elsewhere we compare Accept qualities: a browser
    asking for text/html gets the styled page, while a generic client (or one
    that prefers application/json) keeps receiving the JSON error envelope.
    """
    if request.path.startswith("/api/") or request.path.startswith("/predict"):
        return True
    accept = request.accept_mimetypes
    return accept["text/html"] <= accept["application/json"]


@app.errorhandler(404)
def handle_404(error):
    if _wants_json():
        return jsonify({
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "The requested endpoint does not exist."},
        }), 404
    return render_template("404.html", active_page=""), 404


@app.errorhandler(405)
def handle_405(error):
    return jsonify({
        "success": False,
        "error": {"code": "METHOD_NOT_ALLOWED", "message": "This endpoint does not accept that HTTP method."},
    }), 405


@app.errorhandler(500)
def handle_500(error):
    app.logger.exception("Unhandled server error")
    return jsonify({
        "success": False,
        "error": {"code": "INTERNAL_ERROR", "message": "An unexpected server error occurred."},
    }), 500


# ----------------------------------------------------------------------
# Start-up security review
#
# Reports unsafe configuration without ever printing a secret. Local
# development keeps working; setting ENFORCE_PRODUCTION_CONFIG=true makes
# critical findings fatal.
# ----------------------------------------------------------------------
_findings = review_all(
    dict(app.config),
    is_debug=app.debug,
    host=os.getenv("SERVER_NAME", "localhost"),
)
log_findings(_findings)
assert_production_readiness(
    _findings, enabled=os.getenv("ENFORCE_PRODUCTION_CONFIG", "").lower() in ("1", "true", "yes")
)

# Schema is owned by Alembic (`flask db upgrade`). create_all() is opt-in via
# AUTO_CREATE_SCHEMA so that starting the app against a fresh or partially
# migrated database cannot silently create tables outside the migration
# history. Never enable this in production.
if os.getenv("AUTO_CREATE_SCHEMA", "").strip().lower() in ("1", "true", "yes"):
    with app.app_context():
        db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
