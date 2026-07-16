import pandas as pd

def preprocess_data(df):

    # Make a copy
    df = df.copy()

    # Convert TotalCharges to numeric
    df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")

    # Remove missing values
    df.dropna(inplace=True)

    # Remove customerID
    df.drop("customerID", axis=1, inplace=True)

    # Convert categorical columns into numeric columns
    df = pd.get_dummies(df, drop_first=True)

    return df