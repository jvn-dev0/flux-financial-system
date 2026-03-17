import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix
import joblib

print("Loading dataset: banking_activity_logs.csv")
df = pd.read_csv('banking_activity_logs.csv')

# 1. Preprocessing
# Drop highly specific identifiers that do not help generalize ML patterns
drop_cols = ['LogID', 'AccountID', 'Timestamp', 'Description', 'SessionID', 
             'Username', 'Password', 'FullName', 'Email', 'Phone', 
             'AccountNumber', 'IFSC', 'CreatedAt', 'BeneficiaryName']

print(f"Dropping identifier columns: {drop_cols}")
X = df.drop(columns=[col for col in drop_cols if col in df.columns])

# Target variable is RiskLabel (0 = Normal, 1 = Attack)
y = X.pop('RiskLabel')

# Encode categorical variables (e.g., TransactionType, Channel) into numbers
label_encoders = {}
for col in X.select_dtypes(include=['object']).columns:
    le = LabelEncoder()
    X[col] = le.fit_transform(X[col].astype(str))
    label_encoders[col] = le
    print(f"Encoded categorical feature: {col}")

# Split the dataset: 80% for training the ML model, 20% for testing its accuracy
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

print("\n==============================================")
print("Training Model 1: Random Forest Classifier")
print("==============================================")
# Supervised ML Model: Learns explicitly from the RiskLabels we provided
rf_model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced')
rf_model.fit(X_train, y_train)

y_pred_rf = rf_model.predict(X_test)
print("\nRandom Forest Evaluation Metrics:")
print(classification_report(y_test, y_pred_rf, target_names=["Normal (0)", "Attack (1)"]))

print("\n==============================================")
print("Training Model 2: Isolation Forest")
print("==============================================")
# Unsupervised ML Model: Learns the "shape" of data to find mathematical anomalies
# We set contamination to 'auto' since it only supports up to 0.5
iso_model = IsolationForest(contamination='auto', random_state=42)
iso_model.fit(X_train)

# Predict (-1 = Anomaly/Attack, 1 = Normal)
y_pred_iso = iso_model.predict(X_test)
# Map back to our binary labels for scoring (1 = Attack, 0 = Normal)
y_pred_iso_mapped = [1 if val == -1 else 0 for val in y_pred_iso]

print("\nIsolation Forest Evaluation Metrics:")
print(classification_report(y_test, y_pred_iso_mapped, target_names=["Normal (0)", "Attack (1)"]))

# Save the highest accuracy model
print("\nSaving Random Forest model to disk...")
joblib.dump(rf_model, 'risk_scoring_rf_model.pkl')
joblib.dump(label_encoders, 'label_encoders.pkl')
print("Saved successfully as 'risk_scoring_rf_model.pkl'")

# Extract feature importance from the ML model
print("\n--- ML Model Insights: Top 5 Most Predictive Features ---")
importance = rf_model.feature_importances_
feature_imp = pd.DataFrame({'Feature': X.columns, 'Importance': importance}).sort_values('Importance', ascending=False)
print(feature_imp.head(5).to_string(index=False))
