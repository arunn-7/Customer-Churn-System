import pandas as pd

from app import app
from database.db import db
from models.customer import Customer

with app.app_context():

    # Read dataset
    df = pd.read_csv("data/WA_Fn-UseC_-Telco-Customer-Churn.csv")

    # Clean TotalCharges
    df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")
    df.dropna(inplace=True)

    # Remove old records (optional during development)
    Customer.query.delete()

    # Insert new records
    for _, row in df.iterrows():

        customer = Customer(
            customer_id=row["customerID"],
            gender=row["gender"],
            senior_citizen=row["SeniorCitizen"],
            partner=row["Partner"],
            dependents=row["Dependents"],
            tenure=row["tenure"],
            phone_service=row["PhoneService"],
            multiple_lines=row["MultipleLines"],
            internet_service=row["InternetService"],
            online_security=row["OnlineSecurity"],
            online_backup=row["OnlineBackup"],
            device_protection=row["DeviceProtection"],
            tech_support=row["TechSupport"],
            streaming_tv=row["StreamingTV"],
            streaming_movies=row["StreamingMovies"],
            contract=row["Contract"],
            paperless_billing=row["PaperlessBilling"],
            payment_method=row["PaymentMethod"],
            monthly_charges=row["MonthlyCharges"],
            total_charges=row["TotalCharges"],
            churn=row["Churn"]
        )

        db.session.add(customer)

    db.session.commit()

    print("===================================")
    print("Dataset Imported Successfully!")
    print(f"Customers Imported: {len(df)}")
    print("===================================")