from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sys
import os

# Add the bank directory to path so we can import the shared DatabaseManager
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'bank')))
from database_manager import DatabaseManager

app = Flask(__name__, static_url_path='')
CORS(app)

# Initialize shared DB
db = DatabaseManager()

# --- INITIALIZE ML MODEL ---
try:
    import joblib
    import pandas as pd
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    rf_model_path = os.path.join(BASE_DIR, 'risk_scoring_rf_model.pkl')
    encoders_path = os.path.join(BASE_DIR, 'label_encoders.pkl')
    
    rf_model = joblib.load(rf_model_path)
    label_encoders = joblib.load(encoders_path)
    
    ml_features_expected = [
        'LoginHour', 'FailedLoginCount', 'NewDeviceLogin', 'PasswordChanged', 
        'Channel', 'SessionDuration', 'PagesVisited', 'ClickRate', 
        'RapidTransactions', 'BeneficiaryAdded'
    ]
    print("✅ Local Random Forest Model connected to Admin Backend!")
except Exception as e:
    print(f"⚠️ Warning: Could not load ML models. Ensure .pkl files are in the admin folder. Error: {e}")
    rf_model = None
    label_encoders = None

# --- SERVE STATIC ADMIN HTML ---
@app.route('/')
def index():
    return send_from_directory('', 'login.html')

@app.route('/<path:path>')
def serve_html(path):
    return send_from_directory('', path)

# --- API: AUTHENTICATION ---
@app.route('/api/admin/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    # Hardcoded admin credentials for prototype
    if username == 'admin' and password == 'admin123':
        return jsonify({
            "status": "success",
            "admin_id": "ADM-001",
            "name": "Super Admin"
        })
    return jsonify({"status": "error", "message": "Invalid admin credentials"}), 401

# --- API: DASHBOARD STATS ---
@app.route('/api/admin/stats', methods=['GET'])
def get_dashboard_stats():
    users = db.get_all_users()
    transactions = db.get_all_transactions(limit=1000) # Get a large batch for stats
    
    total_balance = sum(float(u.get('AccountBalance', 0)) for u in users)
    total_users = len(users)
    pending_kyc = len(db.get_pending_kyc_requests())
    
    # Calculate simple transaction volume
    tx_volume = sum(float(t.get('TransactionAmount', 0)) for t in transactions if t.get('TransactionType') == 'Credit')
    
    return jsonify({
        "total_balance": total_balance,
        "total_users": total_users,
        "active_users": total_users, # Mock
        "pending_kyc": pending_kyc,
        "transaction_volume": tx_volume
    })

# --- API: RISK ALERTS ---
@app.route('/api/admin/alerts', methods=['GET'])
def get_high_risk_alerts():
    # 1. Fetch raw un-scored data from ML_Features sheet
    try:
        raw_df = db._load_sheet('ML_Features')
        activity_df = db._load_sheet('ActivityLogs') # To map back to user descriptions
    except Exception as e:
        return jsonify({"error": f"Database read error: {e}"}), 500

    if raw_df.empty or rf_model is None:
        return jsonify({"alerts": []})

    results = []
    
    # We will score the last 100 entries for performance
    recent_data = raw_df.tail(100).copy()
    
    for idx, row in recent_data.iterrows():
        try:
            # Prepare row for ML
            features = {}
            for col in ml_features_expected:
                val = row.get(col, 0)
                # Apply stored label encoders if categorical
                if col in label_encoders:
                    # Handle unseen labels by defaulting to the first seen class to prevent crashes
                    if val in label_encoders[col].classes_:
                        val = label_encoders[col].transform([val])[0]
                    else:
                        val = 0
                else:
                    try:
                        val = float(val) if str(val).strip() != '' else 0.0
                    except:
                        val = 0.0
                features[col] = val
                
            X_input = pd.DataFrame([features])
            
            # Run Random Forest inference
            probabilities = rf_model.predict_proba(X_input)[0]
            # Assuming class layout is [Normal, Suspicious, Attack] or [Normal, Attack]
            # Probabilities usually sum to 1. E.g. index 1 is attack probability
            attack_prob = probabilities[-1] * 100 # percentage scale
            
            if attack_prob > 75:  # High Risk threshold
                # Try to find corresponding log in ActivityLogs roughly around same time
                matching_logs = activity_df[activity_df['CyberRiskScore'] == row.get('CyberRiskScore')] 
                # Note: This matching is a bit brittle without LogID in ML_Features, but functional for prototype
                
                results.append({
                    "Timestamp": "Live (ML Inference)",
                    "CyberRiskScore": float(attack_prob),
                    "AccountID": "? (Live Stream)",
                    "Description": f"AI Detected High Anomalies! Clicks/min: {row.get('ClickRate')}, Failed Logins: {row.get('FailedLoginCount')}"
                })
        except Exception as e:
            pass # Skip rows that fail to parse

    # Sort highest risk first
    results.sort(key=lambda x: x["CyberRiskScore"], reverse=True)
    return jsonify({"alerts": results})

# --- API: TRANSACTIONS ---
@app.route('/api/admin/transactions', methods=['GET'])
def get_all_transactions():
    transactions = db.get_all_transactions(limit=100)
    return jsonify({"transactions": transactions})

# --- API: USERS ---
@app.route('/api/admin/users', methods=['GET'])
def get_all_users():
    users = db.get_all_users()
    return jsonify({"users": users})

# --- API: SYSTEM LOGS ---
@app.route('/api/admin/logs', methods=['GET'])
def get_system_logs():
    return jsonify({"logs": db.get_audit_logs()})

# --- API: KYC MANAGEMENT ---
@app.route('/api/admin/kyc-requests', methods=['GET'])
def get_pending_kyc():
    reqs = db.get_pending_kyc_requests()
    return jsonify({"requests": reqs})

@app.route('/api/admin/kyc-update', methods=['POST'])
def update_kyc():
    data = request.json
    account_id = data.get('account_id')
    new_status = data.get('status') # 'Verified' or 'Rejected'
    
    success, msg = db.update_kyc_status(account_id, new_status)
    if success:
        risk = 50 if new_status == 'Rejected' else 0
        db.log_activity(account_id, {
            "Description": f"Admin (ADM-001) {new_status.lower()} KYC for {account_id}",
            "TransactionType": "System"
        }, risk_score=risk)
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001)) # Run admin on 5001 to avoid clash with bank
    print(f"Starting Admin Panel on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=True)
