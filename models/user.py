"""User model with Flask-Login integration and bcrypt password hashing.

Maps the existing `users` table created by migration 0001_company_workspace:

    id, full_name, email (UNIQUE), password,
    role ENUM('Admin','Analyst','Viewer'), created_at,
    company_id (FK NOT NULL -> companies.id), is_active

Security notes
--------------
* `password` stores a bcrypt hash only. Plaintext is never persisted, logged or
  returned. Flask-Bcrypt 1.x returns `bytes`, so hashes are decoded to `str`
  before they reach the VARCHAR(255) column.
* Every user belongs to exactly one company. `company_id` is NOT NULL at the
  schema level, so cross-tenant membership is impossible by construction.
* Role checks fail closed: an unset, unknown or NULL role grants nothing.
"""

from __future__ import annotations

from flask_login import UserMixin
from sqlalchemy.orm import relationship

from database.db import db
from security.passwords import bcrypt

# Roles permitted by the current policy. Mirrors the DB enum.
ROLE_ADMIN = "Admin"
ROLE_ANALYST = "Analyst"
ROLE_VIEWER = "Viewer"

VALID_ROLES = frozenset({ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER})

# Roles allowed to view the IBM sample/demo dataset.
DEMO_ROLES = frozenset({ROLE_ADMIN, ROLE_ANALYST})


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    # Stored lowercased and whitespace-trimmed. UNIQUE in the database is the
    # final safeguard against duplicate registrations.
    email = db.Column(db.String(100), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_VIEWER)
    created_at = db.Column(db.TIMESTAMP, nullable=False, server_default=db.func.current_timestamp())
    company_id = db.Column(
        db.Integer, db.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    is_active_flag = db.Column("is_active", db.Boolean, nullable=False, default=True, server_default=db.text("1"))

    company = relationship("Company", back_populates="users")

    # ------------------------------------------------------------------
    # Flask-Login
    # ------------------------------------------------------------------
    # UserMixin.get_id() would work on the default PK, but an explicit email
    # based id keeps session payloads stable across backfills.
    def get_id(self) -> str:
        return str(self.id)

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        """Drives Flask-Login's inactive-user rejection.

        Also requires the owning company to be active, so suspending a company
        suspends all of its users.
        """
        if not self.is_active_flag:
            return False
        return bool(self.company.is_usable) if self.company else False

    # ------------------------------------------------------------------
    # Passwords
    # ------------------------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        """Hash with bcrypt. The plaintext is never stored."""
        hashed = bcrypt.generate_password_hash(raw_password)
        # Flask-Bcrypt 1.x returns bytes; the column is VARCHAR.
        self.password = hashed.decode("utf-8") if isinstance(hashed, bytes) else hashed

    def check_password(self, raw_password: str) -> bool:
        """Verify against the stored bcrypt hash. Never raises."""
        if not self.password or raw_password is None:
            return False
        try:
            return bool(bcrypt.check_password_hash(self.password, raw_password))
        except (ValueError, TypeError):
            # Malformed hash in the database must not authenticate anyone.
            return False

    # ------------------------------------------------------------------
    # Roles -- fail closed
    # ------------------------------------------------------------------
    def has_role(self, *roles: str) -> bool:
        """True only for an explicitly recognised role."""
        role = (self.role or "").strip()
        return bool(role) and role in VALID_ROLES and role in roles

    @property
    def is_admin(self) -> bool:
        return self.has_role(ROLE_ADMIN)

    @property
    def is_analyst(self) -> bool:
        return self.has_role(ROLE_ANALYST)

    @property
    def is_viewer(self) -> bool:
        return self.has_role(ROLE_VIEWER)

    @property
    def can_view_demo_data(self) -> bool:
        """Admin and Analyst may view the IBM sample dataset. Viewer may not."""
        role = (self.role or "").strip()
        return role in DEMO_ROLES

    @property
    def company_id_value(self) -> int | None:
        """The authoritative tenant id for this user.

        Returned from the server-side session identity only. It is never read
        from a request parameter.
        """
        return self.company_id if self.company_id is not None else None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User {self.id} {self.email} role={self.role}>"

