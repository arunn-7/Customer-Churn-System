import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean flag from the environment.

    Accepts 1/true/yes/on (case-insensitive) as True. Anything else, including
    an unset variable, yields ``default``.
    """
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:

    SECRET_KEY = os.getenv("SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://"
        f"{os.getenv('DB_USER')}:"
        f"{os.getenv('DB_PASSWORD')}@"
        f"{os.getenv('DB_HOST')}:"
        f"{os.getenv('DB_PORT')}/"
        f"{os.getenv('DB_NAME')}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ------------------------------------------------------------------
    # Cookie security
    #
    # Secure=True requires HTTPS. It is therefore opt-in via COOKIE_SECURE so
    # plain-HTTP local development still works, and MUST be enabled behind a
    # production HTTPS deployment.
    # ------------------------------------------------------------------
    COOKIE_SECURE = _env_bool("COOKIE_SECURE", default=False)

    SESSION_COOKIE_HTTPONLY = True      # not readable from JavaScript
    SESSION_COOKIE_SAMESITE = "Lax"    # blocks cross-site POSTs, allows normal links
    SESSION_COOKIE_SECURE = COOKIE_SECURE

    # Flask-Login "remember me" cookie
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = COOKIE_SECURE
    REMEMBER_COOKIE_DURATION = 60 * 60 * 24 * 14   # 14 days

    # Idle + absolute session lifetimes. A session is invalidated server-side on
    # logout; these bound how long a stolen cookie stays useful.
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8        # 8 hours
    SESSION_REFRESH_EACH_REQUEST = False

    # ------------------------------------------------------------------
    # CSRF (Flask-WTF)
    # ------------------------------------------------------------------
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 60 * 60                   # tokens expire after 1 hour

    # Endpoints that accept JSON from fetch()/curl rather than an HTML form.
    # CSRF protects browser form submissions; these are exempt and instead rely
    # on session cookies + the JSON content type.
    #
    # IMPORTANT: these must be the FULLY QUALIFIED endpoint names. Flask
    # prefixes blueprint routes with the blueprint's name, so a route declared
    # in `predict_bp` (Blueprint("predict", __name__)) is registered as
    # "predict.predict", NOT "predict". Using the short name silently
    # registers no exemption at all, which is what previously made the
    # JavaScript-driven prediction form fail with a CSRF error.
    CSRF_EXEMPT_ENDPOINTS: tuple[str, ...] = (
        "predict.predict",
        "predict.predict_schema",
        "predict.predict_explain",
        "dashboard.api_stats",
        "dashboard.api_analytics",
        "dashboard.api_customers",
        "dashboard.api_customer_detail",
    )
