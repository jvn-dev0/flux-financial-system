from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
import joblib
import os
from database_manager import DatabaseManager

app = Flask(__name__, static_url_path='')
CORS(app) # Enable Cross-Origin requests for local development

# Initialize DB
db = DatabaseManager()

# Load ML Model
try:
    risk_model = joblib.load('risk_model.pkl')
    print("ML Model Loaded Successfully.")
except:
    print("WARNING: risk_model.pkl not found. Risk scoring will be mock.")
    risk_model = None

# --- SERVE STATIC FILES (Frontend) ---
@app.route('/')
def index():
    return send_from_directory('', 'index.html')

@app.route('/user/<path:path>')
def serve_user(path):
    return send_from_directory('user', path)

@app.route('/admin/<path:path>')
def serve_admin(path):
    return send_from_directory('admin', path)

# --- API: AUTHENTICATION ---
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    success, result = db.create_user(
        username=data.get('username'),
        password=data.get('password'),
        full_name=data.get('fullName', 'Unknown'),
        email=data.get('email'),
        phone=data.get('phone')
    )
    if success:
        return jsonify({"status": "success", "user": result}), 201
    return jsonify({"status": "error", "message": result}), 400

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    print(f"DEBUG: Login Attempt for '{username}'")
    
    user = db.get_user(username)
    
    if user:
        # Debug Compare
        stored_pass = str(user['Password'])
        input_pass = str(password)
        print(f"DEBUG: Comparing Password '{input_pass}' vs Stored '{stored_pass}'")
        
        if stored_pass == input_pass:
            print("DEBUG: Password Match Success")
            return jsonify({
                "status": "success",
                "account_id": user['AccountID'],
                "full_name": user['FullName'],
                "role": "user" # Simple role
            })
        else:
            print("DEBUG: Password Mismatch")
            
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

@app.route('/api/auth/change-password', methods=['POST'])
def change_password():
    data = request.json
    account_id = data.get('account_id')
    old_pass = data.get('old_password')
    new_pass = data.get('new_password')
    
    success, msg = db.update_password(account_id, old_pass, new_pass)
    
    if success:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400
@app.route('/api/user/dashboard/<account_id>', methods=['GET'])
def get_dashboard_data(account_id):
    user = db.get_user_by_id(account_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    recent_activity = db.get_recent_activity(account_id)
    
    return jsonify({
        "balance": user['AccountBalance'],
        "kyc_status": user['KYCStatus'],
        "recent_activity": recent_activity
    })

# --- API: TRANSACTIONS (WITH ML RISK SCORING) ---
@app.route('/api/transaction/transfer', methods=['POST'])
def transfer():
    data = request.json
    sender_id = data.get('sender_id')
    amount = float(data.get('amount'))
    
    # 1. Update Balance
    success, msg = db.update_balance(sender_id, -amount)
    if not success:
        return jsonify({"status": "error", "message": msg}), 400

    # 2. Calculate Risk (Using ML Model)
    risk_score = 10 # Default Low
    if risk_model:
        # Construct feature vector matching model schema
        # For demo, we mock the input features based on transaction size
        # Real impl would use 'LoginHour', 'IPRegion' etc from request
        
        # Simple heuristic for demo:
        if amount > 10000:
            risk_score = 85 # High Risk
        elif amount > 5000:
            risk_score = 65 # Medium
        else:
            # Try to use model if features available (Mocking features for now)
            # features = [[...]]
            # risk_score = risk_model.predict(features)[0]
            pass

    # 3. Log Activity
    log_data = {
        "TransactionAmount": amount,
        "TransactionType": "Debit", 
        "Description": f"Transfer to {data.get('recipient_account', 'Unknown')}",
        "SessionID": data.get('session_id', 'SES-UNKNOWN'),
        "LoginHour": 12, # Mock
        "LargeTransaction": 1 if amount > 10000 else 0
    }
    db.log_activity(sender_id, log_data, risk_score)
    
    return jsonify({
        "status": "success",
        "new_balance": msg, # update_balance returns new balance on success
        "risk_score": risk_score
    })

# --- API: DEPOSIT (ADD MONEY) ---
@app.route('/api/transaction/deposit', methods=['POST'])
def deposit():
    try:
        data = request.json
        account_id = data.get('account_id')
        amount = float(data.get('amount'))
        source = data.get('source', 'Unknown')
        
        # 1. Update Balance
        success, msg = db.update_balance(account_id, amount)
        if not success:
            return jsonify({"status": "error", "message": msg}), 400

        # 2. Log Activity
        log_data = {
            "TransactionAmount": amount,
            "TransactionType": "Credit", 
            "Description": f"Deposit via {source}",
            "SessionID": data.get('session_id', 'SES-DEPOSIT'),
            "LoginHour": 12, # Mock
            "LargeTransaction": 1 if amount > 50000 else 0,
            "BeneficiaryAdded": 0
        }
        # Deposits are generally low risk, but large ones might be noted
        risk_score = 10 
        db.log_activity(account_id, log_data, risk_score)
        
        return jsonify({
            "status": "success",
            "new_balance": msg,
            "message": f"Successfully added ${amount} via {source}"
        })
    except Exception as e:
        print(f"ERROR: Deposit Failed: {e}")
        return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500

# --- API: TRANSACTIONS HISTORY ---
@app.route('/api/user/transactions/<account_id>', methods=['GET'])
def get_transactions_history(account_id):
    transactions = db.get_user_transactions(account_id)
    return jsonify({"transactions": transactions})

# --- API: BENEFICIARIES ---
@app.route('/api/user/beneficiaries', methods=['POST'])
def add_beneficiary():
    data = request.json
    success, msg = db.add_beneficiary(
        account_id=data.get('account_id'),
        name=data.get('name'),
        account_number=data.get('account_number'),
        ifsc=data.get('ifsc'),
        nickname=data.get('nickname')
    )
    if success:
        # Log this action as it can be a risk indicator
        db.log_activity(data.get('account_id'), {"BeneficiaryAdded": 1, "Description": f"Added Beneficiary {data.get('name')}"}, 20)
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400

@app.route('/api/user/beneficiaries/<account_id>', methods=['GET'])
def get_beneficiaries(account_id):
    return jsonify({"beneficiaries": db.get_beneficiaries(account_id)})

# --- API: KYC ---
@app.route('/api/user/kyc', methods=['POST'])
def submit_kyc():
    data = request.json
    success, msg = db.submit_kyc(
        account_id=data.get('account_id'),
        doc_type=data.get('doc_type'),
        doc_number=data.get('doc_number')
    )
    if success:
        return jsonify({"status": "success", "message": msg})
    return jsonify({"status": "error", "message": msg}), 400

@app.route('/api/user/kyc-status/<account_id>', methods=['GET'])
def get_kyc_status(account_id):
    status = db.get_kyc_status(account_id)
    return jsonify({"status": "success", "kyc_status": status})

# --- API: ADMIN ---
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    # Hardcoded Admin Credentials for Demo
    if username == 'admin' and password == 'admin123':
        return jsonify({"status": "success", "token": "ADM-TOKEN-X99", "role": "admin"})
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

@app.route('/api/admin/stats', methods=['GET'])
def get_admin_stats():
    users = db.get_all_users()
    logs = db._load_sheet('ActivityLogs') # Accessing directly for stats
    
    total_users = len(users)
    active_users = len([u for u in users if u['AccountBalance'] > 0]) # Mock definition
    flagged_tx = len(logs[logs['CyberRiskScore'] > 50])
    pending_kyc = len([u for u in users if u['KYCStatus'] == 'Pending'])
    
    return jsonify({
        "total_users": total_users,
        "active_sessions": active_users, # Mock
        "flagged_transactions": flagged_tx,
        "pending_kyc": pending_kyc
    })

@app.route('/api/admin/users', methods=['GET'])
def get_all_users_admin():
    users = db.get_all_users()
    return jsonify({"users": users})

    alerts = db.get_high_risk_alerts()
    return jsonify({"alerts": alerts})

@app.route('/api/admin/transactions', methods=['GET'])
def get_admin_transactions():
    tx = db.get_all_transactions(limit=50)
    return jsonify({"transactions": tx})

@app.route('/api/admin/logs', methods=['GET'])
def get_admin_logs():
    logs = db.get_audit_logs()
    return jsonify({"logs": logs})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
