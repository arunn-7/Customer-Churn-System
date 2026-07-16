from database.db import db

class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)

    customer_id = db.Column(db.String(20), unique=True, nullable=False)
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
    churn = db.Column(db.String(5))
