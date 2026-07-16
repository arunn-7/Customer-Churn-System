import pandas as pd

def load_dataset():
    file_path = "data/WA_Fn-UseC_-Telco-Customer-Churn.csv"

    df = pd.read_csv(file_path)

    # Convert TotalCharges to numeric
    df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")

    # Remove rows where TotalCharges is missing
    df.dropna(inplace=True)

    print("=" * 60)
    print("Dataset Cleaned Successfully!")
    print("=" * 60)

    print(f"Rows : {df.shape[0]}")
    print(f"Columns : {df.shape[1]}")

    print("\nData Types:")
    print(df.dtypes)

    return df