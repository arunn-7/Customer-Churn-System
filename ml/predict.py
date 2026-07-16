import joblib
import pandas as pd

# Load trained model
model = joblib.load("ml/model.pkl")


def predict_customer(data):

    # Convert input to DataFrame
    df = pd.DataFrame([data])

    # Prediction
    prediction = model.predict(df)[0]

    # Probability
    probability = model.predict_proba(df)[0][1]

    if prediction:
        result = "Yes"
    else:
        result = "No"

    return {
        "Prediction": result,
        "Probability": float(round(probability * 100, 2))
    }


# Test
if __name__ == "__main__":

    sample = {
        "SeniorCitizen": 0,
        "tenure": 12,
        "MonthlyCharges": 75.25,
        "TotalCharges": 900.50,

        "gender_Male": True,
        "Partner_Yes": False,
        "Dependents_Yes": False,
        "PhoneService_Yes": True,
        "MultipleLines_No phone service": False,
        "MultipleLines_Yes": True,
        "InternetService_Fiber optic": True,
        "InternetService_No": False,
        "OnlineSecurity_No internet service": False,
        "OnlineSecurity_Yes": False,
        "OnlineBackup_No internet service": False,
        "OnlineBackup_Yes": True,
        "DeviceProtection_No internet service": False,
        "DeviceProtection_Yes": False,
        "TechSupport_No internet service": False,
        "TechSupport_Yes": False,
        "StreamingTV_No internet service": False,
        "StreamingTV_Yes": True,
        "StreamingMovies_No internet service": False,
        "StreamingMovies_Yes": True,
        "Contract_One year": False,
        "Contract_Two year": False,
        "PaperlessBilling_Yes": True,
        "PaymentMethod_Credit card (automatic)": False,
        "PaymentMethod_Electronic check": True,
        "PaymentMethod_Mailed check": False
    }

    print(predict_customer(sample))