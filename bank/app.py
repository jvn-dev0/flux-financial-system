from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd
import os
from database_manager import DatabaseManager

app = Flask(__name__, static_url_path='')
CORS(app) # Enable Cross-Origin requests for local development

# Initialize DB
db = DatabaseManager()

# ML Model Loading has been removed. Risk scoring will be mock.
risk_model = None
schema_features = None

# --- SERVE STATIC FILES (Frontend) ---
@app.route('/')
def index():
    return send_from_directory('', 'index.html')

@app.route('/user/<path:path>')
def serve_user(path):
    return send_from_directory('user', path)


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
            # Log failed login attempt
            db.log_activity(user['AccountID'], {
                "FailedLoginCount": 1, 
                "Description": "Failed login attempt (Wrong password)",
                "SessionID": "SES-LOGIN-FAIL"
            }, risk_score=0)
            
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401
    
    # Username not found
    print(f"DEBUG: Username '{username}' Not Found")
    db.log_activity("UNKNOWN", {
        "FailedLoginCount": 1, 
        "Description": f"Failed login attempt (Unknown user: {username})",
        "SessionID": "SES-LOGIN-FAIL"
    }, risk_score=0)
    
    return jsonify({"status": "error", "message": "Invalid credentials"}), 401

@app.route('/api/auth/change-password', methods=['POST'])
def change_password():
    data = request.json
    account_id = data.get('account_id')
    old_pass = data.get('old_password')
    new_pass = data.get('new_password')
    
    success, msg = db.update_password(account_id, old_pass, new_pass)
    
    if success:
        # Log successful password change
        db.log_activity(account_id, {
            "PasswordChanged": 1,
            "Description": "User successfully changed password",
            "SessionID": "SES-PASS-CHANGE"
        }, risk_score=10)
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
        "account_number": user.get('AccountNumber', 'Not Assigned'),
        "ifsc": user.get('IFSC', 'Not Assigned'),
        "recent_activity": recent_activity
    })

# --- API: TRANSACTIONS (WITH ML RISK SCORING) ---
@app.route('/api/transaction/transfer', methods=['POST'])
def transfer():
    data = request.json
    sender_id = data.get('sender_id')
    amount = float(data.get('amount'))
    recipient_acc = data.get('recipient_account')
    recipient_ifsc = data.get('recipient_ifsc')
    
    # 0. Validate Recipient
    is_valid, recipient_id_or_msg = db.validate_account(recipient_acc, recipient_ifsc)
    if not is_valid:
        return jsonify({"status": "error", "message": recipient_id_or_msg}), 400

    # 1. Update Sender Balance (Debit)
    success, msg = db.update_balance(sender_id, -amount)
    if not success:
        return jsonify({"status": "error", "message": msg}), 400
        
    # 1.5 Update Receiver Balance (Credit)
    db.update_balance(recipient_id_or_msg, amount)

    # 2. Calculate Risk (Using Mock Logic)
    risk_score = 10 # Default Low
    
    # Simple Mock Risk based solely on amount
    if amount > 50000:
        risk_score = 75
        print(f"--- MOCK RISK PREDICTION ---")
        print(f"High Amount Detected: {amount}, Risk Flagged")
    elif amount > 10000:
        risk_score = 40
        print(f"--- MOCK RISK PREDICTION ---")
        print(f"Medium Amount Detected: {amount}")
    
    # 3. Log Activity for Sender (Debit)
    log_data_sender = {
        "TransactionAmount": amount,
        "TransactionType": "Debit", 
        "Description": f"Transfer to ACC: {recipient_acc} (IFSC: {recipient_ifsc})",
        "SessionID": data.get('session_id', 'SES-UNKNOWN'),
        "ClickRate": data.get('click_rate', 0),
        "PagesVisited": data.get('pages_visited', 1),
        "SessionDuration": data.get('session_duration', 0),
        "DeviceTrustScore": data.get('device_trust_score', 100),
        "Channel": data.get('channel', 'Web'),
        "NewDeviceLogin": data.get('new_device_login', 0),
        "RapidTransactions": data.get('rapid_transactions', 0)
    }
    db.log_activity(sender_id, log_data_sender, risk_score)

    # 4. Log Activity for Recipient (Credit)
    sender_user = db.get_user_by_id(sender_id)
    sender_name = sender_user.get('FullName', 'Unknown Sender') if sender_user else 'Unknown Sender'
    
    log_data_recipient = {
        "TransactionAmount": amount,
        "TransactionType": "Credit", 
        "Description": f"Transfer from {sender_name}",
        "SessionID": data.get('session_id', 'SES-UNKNOWN')
    }
    db.log_activity(recipient_id_or_msg, log_data_recipient, 10) # Risk for receiving is low
    
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
            "ClickRate": data.get('click_rate', 0),
            "PagesVisited": data.get('pages_visited', 1),
            "SessionDuration": data.get('session_duration', 0),
            "DeviceTrustScore": data.get('device_trust_score', 100),
            "Channel": data.get('channel', 'Web'),
            "NewDeviceLogin": data.get('new_device_login', 0),
            "RapidTransactions": data.get('rapid_transactions', 0)
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
    try:
        data = request.json
        
        # 0. Validate Bank Details
        is_valid, _ = db.validate_account(data.get('account_number'), data.get('ifsc'))
        if not is_valid:
            return jsonify({"status": "error", "message": "Invalid Account Number or IFSC Code. Receiver not found."}), 400
            
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
    except Exception as e:
        print(f"ERROR in Add Beneficiary: {e}")
        return jsonify({"status": "error", "message": f"Server Error: {str(e)}"}), 500

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


# =============================================================================
# ADMIN ROUTES (merged here so Render serves them from the same process)
# =============================================================================

ADMIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'admin')

@app.route('/admin')
@app.route('/admin/')
def admin_index():
    return send_from_directory(ADMIN_DIR, 'login.html')

@app.route('/admin/<path:path>')
def serve_admin(path):
    return send_from_directory(ADMIN_DIR, path)

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    if username == 'admin' and password == 'admin123':
        return jsonify({"status": "success", "admin_id": "ADM-001", "name": "Super Admin"})
    return jsonify({"status": "error", "message": "Invalid admin credentials"}), 401

@app.route('/api/admin/stats', methods=['GET'])
def get_admin_stats():
    def safe_float(val):
        try:
            return float(val) if str(val).strip() != '' else 0.0
        except:
            return 0.0

    users = db.get_all_users()
    transactions = db.get_all_transactions(limit=1000)

    total_balance = sum(safe_float(u.get('AccountBalance', 0)) for u in users)
    total_users = len(users)
    pending_kyc = len(db.get_pending_kyc_requests())

    tx_volume = sum(safe_float(t.get('TransactionAmount', 0)) for t in transactions if t.get('TransactionType') == 'Credit')

    recent_tx = db.get_all_transactions(limit=200)
    blocked_users = {str(u.get('AccountID')) for u in users if u.get('Status') == 'Blocked'}

    flagged = 0
    for t in recent_tx:
        try:
            if float(t.get('CyberRiskScore', 0)) > 75:
                if str(t.get('AccountID')) not in blocked_users:
                    flagged += 1
        except:
            pass

    return jsonify({
        "total_balance": total_balance,
        "total_users": total_users,
        "active_users": total_users,
        "pending_kyc": pending_kyc,
        "transaction_volume": tx_volume,
        "flagged_transactions": flagged
    })

@app.route('/api/admin/transactions', methods=['GET'])
def get_admin_transactions():
    transactions = db.get_all_transactions(limit=100)
    users = db.get_all_users()
    blocked_users = {str(u.get('AccountID')) for u in users if u.get('Status') == 'Blocked'}

    for t in transactions:
        if str(t.get('AccountID')) in blocked_users:
            t['CyberRiskScore'] = 0
            if not str(t.get('Description', '')).startswith('[BLOCKED]'):
                t['Description'] = "[BLOCKED] " + str(t.get('Description', ''))

    return jsonify({"transactions": transactions})

@app.route('/api/admin/users', methods=['GET'])
def get_admin_users():
    users = db.get_all_users()
    return jsonify({"users": users})

@app.route('/api/admin/user/<account_id>', methods=['GET'])
def get_admin_user_analytics(account_id):
    user = db.get_user_by_id(account_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    all_activity = db.get_user_transactions(account_id)
    transfers = [log for log in all_activity if log.get('TransactionType') == 'Transfer']
    total_spend = sum([float(log.get('TransactionAmount', 0)) for log in transfers])
    avg_txn = total_spend / len(transfers) if len(transfers) > 0 else 0.0

    try:
        b_df = db._load_sheet('Beneficiaries')
        ben_count = len(b_df[b_df['AccountID'] == account_id]) if not b_df.empty and 'AccountID' in b_df.columns else 0
    except:
        ben_count = 0

    return jsonify({
        "status": "success",
        "total_spend": round(total_spend, 2),
        "avg_transaction": round(avg_txn, 2),
        "beneficiaries": ben_count,
        "kyc_status": user.get('KYCStatus', 'Pending'),
        "recent_activity": all_activity[:5]
    })

@app.route('/api/admin/action', methods=['POST'])
def log_admin_action():
    data = request.json
    action = data.get('action')
    account_id = data.get('account_id')

    if account_id and account_id != '? (Live Stream)':
        db.log_activity(account_id, {
            "Description": f"Admin (ADM-001) {action} user {account_id}",
            "TransactionType": "System"
        }, risk_score=100 if action == 'Blocked' else 0)
        if action == 'Blocked':
            db.update_user_status(account_id, 'Blocked')

    return jsonify({"status": "success"})

@app.route('/api/admin/logs', methods=['GET'])
def get_admin_logs():
    return jsonify({"logs": db.get_audit_logs()})

@app.route('/api/admin/kyc-requests', methods=['GET'])
def get_admin_pending_kyc():
    reqs = db.get_pending_kyc_requests()
    return jsonify({"requests": reqs})

@app.route('/api/admin/kyc-update', methods=['POST'])
def admin_update_kyc():
    data = request.json
    account_id = data.get('account_id')
    new_status = data.get('status')

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
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

