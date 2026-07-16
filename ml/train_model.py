import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

from preprocess import preprocess_data

# Load dataset
df = pd.read_csv("data/WA_Fn-UseC_-Telco-Customer-Churn.csv")

# Preprocess
df = preprocess_data(df)

print(df.head())
print(df.dtypes)

# Target column
y = df["Churn_Yes"]

# Features
X = df.drop("Churn_Yes", axis=1)

# Split
X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42
)

# Train
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

models = {
    "Logistic Regression": LogisticRegression(max_iter=1000),
    "Random Forest": RandomForestClassifier(random_state=42),
    "Gradient Boosting": GradientBoostingClassifier(random_state=42)
}

for name, model in models.items():

    model.fit(X_train, y_train)

    prediction = model.predict(X_test)

    accuracy = accuracy_score(y_test, prediction)

    print(f"\n{name}")
    print(f"Accuracy: {accuracy:.4f}")
# Predict
prediction = model.predict(X_test)

print("Accuracy:", accuracy_score(y_test, prediction))

import joblib

best_model = GradientBoostingClassifier(random_state=42)

best_model.fit(X_train, y_train)

joblib.dump(best_model, "ml/model.pkl")

print("\nBest model saved successfully!")