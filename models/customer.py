from sqlalchemy.orm import relationship

from database.db import db


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)

    # --- tenancy -------------------------------------------------------
    # Added by migration 0001_company_workspace. company_id IS NULL marks the
    # IBM sample dataset, which stays separate from company-owned records.
    company_id = db.Column(
        db.Integer, db.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=True
    )
    source = db.Column(
        db.String(20), nullable=False, default="ibm_sample", server_default="ibm_sample"
    )
    created_at = db.Column(
        db.TIMESTAMP, nullable=False, server_default=db.func.current_timestamp()
    )
    updated_at = db.Column(
        db.TIMESTAMP, nullable=True, onupdate=db.func.current_timestamp()
    )

    customer_id = db.Column(db.String(20), nullable=False)
    gender = db.Column(db.String(10))
    senior_citizen = db.Column(db.Integer)
    partner = db.Column(db.String(5))
    dependents = db.Column(db.String(5))
    tenure = db.Column(db.Integer)
    phone_service = db.Column(db.String(5))
    multiple_lines = db.Column(db.String(30))
    internet_service = db.Column(db.String(30))
    online_security = db.Column(db.String(30))
    online_backup = db.Column(db.String(30))
    device_protection = db.Column(db.String(30))
    tech_support = db.Column(db.String(30))
    streaming_tv = db.Column(db.String(30))
    streaming_movies = db.Column(db.String(30))
    contract = db.Column(db.String(30))
    paperless_billing = db.Column(db.String(5))
    payment_method = db.Column(db.String(100))
    monthly_charges = db.Column(db.Float)
    total_charges = db.Column(db.Float)
    # Ground-truth churn label. NULL for imported company data, where the
    # outcome is a model *prediction* rather than an observed fact.
    churn = db.Column(db.String(5))

    company = relationship("Company", back_populates="customers")

    # ---------------------------------------------------------------
    # Scope helpers
    # ---------------------------------------------------------------
    @property
    def is_sample_data(self) -> bool:
        """True for the IBM demo dataset (no owning company)."""
        return self.company_id is None

    @property
    def owns_predictions(self) -> bool:
        """Predicted outcomes stay separate from the actual label above."""
        return self.churn is None
