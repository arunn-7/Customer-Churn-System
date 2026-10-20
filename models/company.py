"""Company (tenant root) model.

Maps the existing `companies` table created by migration 0001_company_workspace.
No schema change was required to model it.
"""

from __future__ import annotations

from sqlalchemy.orm import relationship

from database.db import db


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    # Unique per tenant; company *names* are intentionally not unique.
    slug = db.Column(db.String(64), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.text("1"))
    created_at = db.Column(db.TIMESTAMP, nullable=False, server_default=db.func.current_timestamp())

    users = relationship(
        "User", back_populates="company", lazy="dynamic", cascade="all, delete-orphan"
    )
    customers = relationship(
        "Customer", back_populates="company", lazy="dynamic"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Company {self.id} {self.slug}>"

    @property
    def is_usable(self) -> bool:
        """A company must be active before its users may sign in."""
        return bool(self.is_active)
