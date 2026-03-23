import gspread
import os
import pandas as pd
from datetime import datetime
import pytz
from oauth2client.service_account import ServiceAccountCredentials

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "flux_financial_database.xlsx")
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
GOOGLE_SHEET_ID = "1f4Qk6s50pDmRMyH7pMXzPqKk6Jp7VaTPHRfNTIxk8Eg" # User provided ID

class DatabaseManager:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.use_cloud = False
        self.gc = None
        self.sh = None
        
        self._cache = {}
        self._cache_time = {}
        self.CACHE_TTL = 15 # Fetch from Google Sheets max every 15 seconds
        
        # Try to connect to Google Sheets
        creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
        
        try:
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = None
            
            if creds_json:
                # Load from Environment Variable (Render / Production)
                import json, base64
                
                # First, try to decode as base64 (most reliable approach - no newline issues)
                creds_dict = None
                try:
                    decoded = base64.b64decode(creds_json.strip()).decode('utf-8')
                    creds_dict = json.loads(decoded)
                    print("--- LOADED CREDENTIALS FROM BASE64 ENVIRONMENT VARIABLE ---")
                except Exception:
                    pass
                
                # Fallback: try parsing as raw JSON
                if creds_dict is None:
                    try:
                        creds_dict = json.loads(creds_json, strict=False)
                    except json.JSONDecodeError:
                        # Last resort: try fixing common escaping issues
                        fixed_json = creds_json.strip().replace("'", '"')
                        creds_dict = json.loads(fixed_json, strict=False)
                    
                    # Fix for Render escaping the newlines in the private key
                    if creds_dict and 'private_key' in creds_dict:
                        creds_dict['private_key'] = creds_dict['private_key'].replace('\\n', '\n')
                    print("--- LOADED CREDENTIALS FROM JSON ENVIRONMENT VARIABLE ---")
                    
                creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
                print("--- GOOGLE CREDENTIALS LOADED SUCCESSFULLY ---")
            elif os.path.exists(CREDENTIALS_FILE):
                # Load from Local File (Development)
                creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
                print("--- LOADED CREDENTIALS FROM LOCAL FILE ---")
            
            if creds:
                self.gc = gspread.authorize(creds)
                
                # Try open sheet by ID
                try:
                    self.sh = self.gc.open_by_key(GOOGLE_SHEET_ID)
                    print(f"--- CONNECTED TO GOOGLE SHEETS (ID: {GOOGLE_SHEET_ID}) ---")
                    
                    # Rename it if needed (User asked to "name it")
                    if self.sh.title != "Flux Financial Database":
                        self.sh.update_title("Flux Financial Database")
                        
                except gspread.SpreadsheetNotFound:
                    print("Error: The Sheet ID exists but I cannot access it. Did you share it with the Service Account email?")
                except Exception as e:
                     print(f"Error opening sheet: {e}")
                
                if self.sh:
                    self.use_cloud = True
            
        except Exception as e:
            print(f"Cloud Connection Failed: {e}")
                
        if not self.use_cloud:
            print("--- USING LOCAL EXCEL FILE (OFFLINE MODE) ---")
            if not os.path.exists(self.db_file):
                print(f"WARNING: Database file {self.db_file} not found. Operating with empty data in-memory.")
                try:
                    import pandas as pd
                    pd.DataFrame().to_excel(self.db_file)
                except Exception as e:
                    print(f"Failed to create dummy excel file: {e}")

    def _load_sheet(self, sheet_name):
        import time
        current_time = time.time()
        
        # Serve from fast local cache if under TTL
        if sheet_name in self._cache and (current_time - self._cache_time.get(sheet_name, 0)) < self.CACHE_TTL:
            return self._cache[sheet_name].copy()

        if self.use_cloud:
            try:
                ws = self.sh.worksheet(sheet_name)
                data = ws.get_all_records()
                if not data:
                    headers = ws.row_values(1)
                    df = pd.DataFrame(columns=headers)
                else:
                    df = pd.DataFrame(data)
                
                # Update Cache
                self._cache[sheet_name] = df.copy()
                self._cache_time[sheet_name] = current_time
                return df
                
            except gspread.WorksheetNotFound:
                 return pd.DataFrame() 
            except Exception as e:
                print(f"Error loading sheet {sheet_name}: {e}")
                # Fallback to expired cache if Google API rate limits us
                if sheet_name in self._cache:
                    return self._cache[sheet_name].copy()
                return pd.DataFrame() 
        else:
            try:
                df = pd.read_excel(self.db_file, sheet_name=sheet_name, engine='openpyxl')
                self._cache[sheet_name] = df.copy()
                self._cache_time[sheet_name] = current_time
                return df
            except Exception:
                if sheet_name in self._cache:
                    return self._cache[sheet_name].copy()
                return pd.DataFrame()

    def _save_sheet(self, df, sheet_name):
        import time
        # Instantly update local cache whenever we save, ensuring it's never stale
        self._cache[sheet_name] = df.copy()
        self._cache_time[sheet_name] = time.time()
        
        if self.use_cloud:
            try:
                try:
                    ws = self.sh.worksheet(sheet_name)
                    ws.clear()
                except gspread.WorksheetNotFound:
                    ws = self.sh.add_worksheet(title=sheet_name, rows=100, cols=20)
                
                # Convert DataFrame to List of Lists
                # Handle timestamps/NaNs
                df = df.fillna('')
                # Convert datetime objects to string
                for col in df.select_dtypes(include=['datetime64']).columns:
                    df[col] = df[col].astype(str)
                    
                data = [df.columns.values.tolist()] + df.values.tolist()
                ws.update(range_name='A1', values=data)
            except Exception as e:
                print(f"Error saving to Cloud: {e}")
        else:
            # Local Save Logic
            all_sheets = pd.read_excel(self.db_file, sheet_name=None, engine='openpyxl')
            all_sheets[sheet_name] = df
            
            with pd.ExcelWriter(self.db_file, engine='openpyxl') as writer:
                for name, data in all_sheets.items():
                    data.to_excel(writer, sheet_name=name, index=False)

    # --- USER AUTHENTICATION ---
    def create_user(self, username, password, full_name, email, phone):
        df = self._load_sheet('Users')
        
        # Check if username exists (Case Insensitive)
        # Convert column to string and lower for comparison
        if not df.empty and 'Username' in df.columns:
            existing_users = df['Username'].astype(str).str.lower().values
            if str(username).lower() in existing_users:
                print(f"DEBUG: Username '{username}' already exists.")
                return False, "Username already exists"

        # Generate IDs
        new_id = f"AC{len(df) + 1001}"
        
        import random
        import string
        from datetime import datetime
        
        # 11-digit random account number for uniqueness
        acc_num = str(random.randint(10000000000, 99999999999))
        
        # 11-character unique IFSC: standard bank code FLUX + 0 + random 6 chars
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        ifsc_code = f"FLUX0{suffix}"
        
        new_user = {
            "AccountID": new_id,
            "AccountNumber": acc_num,
            "IFSC": ifsc_code,
            "Username": username, # Store original casing for display
            "Password": str(password), # Force String
            "FullName": full_name,
            "Email": email,
            "Phone": str(phone), # Force string to prevent pandas type errors
            "AccountBalance": 0.0, # Start with 0
            "KYCStatus": "Not Started",
            "CreatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        print(f"DEBUG: Creating User: {new_user}")
        
        # Use simple concat, safe for empty dataframes
        new_row_df = pd.DataFrame([new_user])
        if df.empty:
            df = new_row_df
        else:
            df = pd.concat([df, new_row_df], ignore_index=True)
            
        self._save_sheet(df, 'Users')
        return True, new_user

    def get_user(self, username):
        df = self._load_sheet('Users')
        
        # Check if DB is completely empty (no columns)
        if df.empty or 'Username' not in df.columns:
            print(f"DEBUG: Login Failed - Database empty or missing Username column.")
            return None
        
        # Case Insensitive Lookup
        # We look for a row where Lower(Username) == Lower(Input)
        # But return the actual row data
        
        # Safe string conversion
        df['Username_Lower'] = df['Username'].astype(str).str.lower()
        search_key = str(username).lower()
        
        user_row = df[df['Username_Lower'] == search_key]
        
        if user_row.empty:
            print(f"DEBUG: Login Failed - Username '{username}' not found.")
            return None
            
        print(f"DEBUG: User Found: {user_row.iloc[0]['Username']}")
        return user_row.iloc[0].to_dict()

    def get_user_by_id(self, account_id):
        df = self._load_sheet('Users')
        user = df[df['AccountID'] == account_id]
        if user.empty:
            return None
        return user.iloc[0].to_dict()

    def update_balance(self, account_id, amount):
        # Amount can be negative (withdrawal) or positive (deposit)
        df = self._load_sheet('Users')
        
        if account_id not in df['AccountID'].values:
            return False, "User not found"
            
        index = df[df['AccountID'] == account_id].index[0]
        current_balance = df.at[index, 'AccountBalance']
        
        if current_balance + amount < 0:
            return False, "Insufficient funds"
            
        df.at[index, 'AccountBalance'] = current_balance + amount
        self._save_sheet(df, 'Users')
        return True, float(df.at[index, 'AccountBalance'])

    def validate_account(self, account_number, ifsc):
        df = self._load_sheet('Users')
        if 'AccountNumber' not in df.columns or 'IFSC' not in df.columns:
            return False, "System uninitialized for this check."
            
        # Clean inputs
        acc_str = str(account_number).strip().split('.')[0]
        ifsc_str = str(ifsc).strip().upper()
        
        # Clean Database Columns for matching
        df_acc = df['AccountNumber'].astype(str).str.strip().str.split('.').str[0]
        df_ifsc = df['IFSC'].astype(str).str.strip().str.upper()
            
        match = df[(df_acc == acc_str) & (df_ifsc == ifsc_str)]
                   
        if match.empty:
            return False, "Invalid Account Number or IFSC Code."
            
        return True, match.iloc[0]['AccountID']

    def update_password(self, account_id, old_password, new_password):
        df = self._load_sheet('Users')
        
        if account_id not in df['AccountID'].values:
            return False, "User not found"
            
        index = df[df['AccountID'] == account_id].index[0]
        stored_password = str(df.at[index, 'Password'])
        
        if stored_password != str(old_password):
            return False, "Incorrect current password"
            
        df.at[index, 'Password'] = str(new_password)
        self._save_sheet(df, 'Users')
        return True, "Password updated successfully"

    # --- LOGGING & RISK ---
    def log_activity(self, account_id, activity_data, risk_score):
        df = self._load_sheet('ActivityLogs')
        
        ist = pytz.timezone('Asia/Kolkata')
        current_time = datetime.now(ist)
        
        new_log = {
            "LogID": f"LOG-{len(df) + 1}",
            "AccountID": account_id,
            "Timestamp": current_time.strftime("%Y-%m-%d %H:%M:%S"),
            "CyberRiskScore": risk_score
        }
        
        # Merge basic activity data (SessionID, Amount, etc.)
        new_log.update(activity_data)
        
        # Filter out ML-specific metrics to completely safeguard ActivityLogs
        ml_only_cols = ['FailedLoginCount', 'BeneficiaryAdded', 'account', 'ClickRate', 'PagesVisited', 
                        'LoginHour', 'RapidTransactions', 'NewDeviceLogin', 'PasswordChanged', 'Channel', 
                        'SessionDuration', 'DeviceTrustScore', 'RiskLabel']
        activity_row = {k: v for k, v in new_log.items() if k not in ml_only_cols}
        
        # Fill missing columns with 0 or default to verify schema compliance
        for col in df.columns:
            if col not in activity_row:
                activity_row[col] = 0
                
        df = pd.concat([df, pd.DataFrame([activity_row])], ignore_index=True)
        
        # Extra safety measure: drop rogue columns if the DataFrame inherited them
        for drop_col in ml_only_cols:
            if drop_col in df.columns:
                df = df.drop(columns=[drop_col])
                
        self._save_sheet(df, 'ActivityLogs')

        # --- Write targeted subset to ML_Features ---
        try:
            ml_df = self._load_sheet('ML_Features')
            ml_columns = [
                'AccountBalance', 'KYCStatus', 'TransactionType', 'TransactionAmount', 
                'SessionDuration', 'LoginHour', 'FailedLoginCount', 'NewDeviceLogin', 
                'PasswordChanged', 'Channel', 'PagesVisited', 'ClickRate', 
                'RapidTransactions', 'BeneficiaryAdded', 'LargeTransaction', 
                'DeviceTrustScore', 'CyberRiskScore'
            ]
            
            # Fetch user context for base features
            user_info = self.get_user_by_id(account_id) or {}
            
            ml_row = {}
            for col in ml_columns:
                if col in new_log:
                    ml_row[col] = new_log[col]
                elif col == 'TransactionAmount' and 'TransactionAmount' not in new_log:
                    ml_row[col] = 0
                elif col == 'TransactionType' and 'TransactionType' not in new_log:
                    ml_row[col] = 'Transfer' # Default safe fallback
                elif col == 'AccountBalance':
                    ml_row[col] = user_info.get('AccountBalance', 0)
                elif col == 'KYCStatus':
                    ml_row[col] = user_info.get('KYCStatus', 'Verified') # Cannot predict effectively on '0'
                elif col == 'LargeTransaction':
                    amt = new_log.get('TransactionAmount', 0)
                    ml_row[col] = 1 if amt > 100000 else 0
                else:
                    ml_row[col] = 0 # Fallback 
            
            # Explicitly set LoginHour based on correct live time
            ist = pytz.timezone('Asia/Kolkata')
            now_dt = datetime.now(ist)
            ml_row['LoginHour'] = now_dt.hour
            ml_row['AccountID'] = account_id # CRITICAL: Add AccountID so it can be matched later
            
            # --- ROW UPDATING LOGIC FOR FAILED LOGINS ---
            # If this is a failed login, check if a row for this AccountID and LoginHour exists
            # We look at the last 10 rows to see if we should 'update' instead of 'append'
            if ml_row.get('FailedLoginCount', 0) > 0 and not ml_df.empty:
                # Find the most recent record for this user in this hour
                mask = (ml_df['AccountID'] == account_id) & (ml_df['LoginHour'] == ml_row['LoginHour'])
                if mask.any():
                    idx = ml_df[mask].index[-1]
                    # Update existing row
                    ml_df.at[idx, 'FailedLoginCount'] = ml_df.at[idx, 'FailedLoginCount'] + ml_row['FailedLoginCount']
                    ml_df.at[idx, 'CyberRiskScore'] = max(ml_df.at[idx, 'CyberRiskScore'], ml_row['CyberRiskScore'])
                    print(f"DEBUG: Updated existing ML row for {account_id} (New count: {ml_df.at[idx, 'FailedLoginCount']})")
                else:
                    ml_df = pd.concat([ml_df, pd.DataFrame([ml_row])], ignore_index=True)
            else:
                ml_df = pd.concat([ml_df, pd.DataFrame([ml_row])], ignore_index=True)
                
            self._save_sheet(ml_df, 'ML_Features')
        except Exception as e:
            print(f"DEBUG: Failed to write to ML_Features: {e}")

        return True

    def get_recent_activity(self, account_id, limit=5):
        df = self._load_sheet('ActivityLogs')
        if 'AccountID' not in df.columns: return [] # Handle empty case
        user_logs = df[df['AccountID'] == account_id].sort_values(by='Timestamp', ascending=False)
        return user_logs.head(limit).to_dict('records')

    def get_user_transactions(self, account_id):
        df = self._load_sheet('ActivityLogs')
        if 'AccountID' not in df.columns: return []
        user_logs = df[df['AccountID'] == account_id].sort_values(by='Timestamp', ascending=False)
        
        # Ensure optional columns exist for clean frontend
        if 'Description' not in user_logs.columns: user_logs['Description'] = 'Transaction'
        if 'TransactionType' not in user_logs.columns: user_logs['TransactionType'] = 'Debit' # Default hack for old data
        
        return user_logs.to_dict('records')

    def get_audit_logs(self):
        # In a real app, this would be a separate 'AuditLogs' sheet.
        # For now, we'll filter 'ActivityLogs' for Admin actions (if any)
        # OR just return high-level system events.
        # Let's create a visual mock from recent high-risk events for now.
        df = self._load_sheet('ActivityLogs')
        admin_actions = df[df['Description'].str.contains('Admin|Blocked|Dismissed', na=False, case=False)]
        return admin_actions.sort_values(by='Timestamp', ascending=False).to_dict('records')

    # --- ADMIN ---
    def get_all_users(self):
        return self._load_sheet('Users').to_dict('records')
    
    def get_high_risk_alerts(self):
        df = self._load_sheet('ActivityLogs')
        # Filter for Score > 75 (High Risk)
        alerts = df[df['CyberRiskScore'] > 75].sort_values(by='Timestamp', ascending=False)
        return alerts.to_dict('records')

    def get_all_transactions(self, limit=50):
        df = self._load_sheet('ActivityLogs')
        if df.empty or 'Timestamp' not in df.columns:
            return []
        # Sort by latest
        tx = df.sort_values(by='Timestamp', ascending=False).head(limit)
        
        # Ensure calculated columns exist
        if 'Description' not in tx.columns: tx['Description'] = 'Transaction'
        if 'CyberRiskScore' not in tx.columns: tx['CyberRiskScore'] = 0
        
        return tx.to_dict('records')

    # --- BENEFICIARIES ---
    def add_beneficiary(self, account_id, name, account_number, ifsc, nickname):
        df = self._load_sheet('Beneficiaries')
        
        # Check if already exists for this user
        if 'AccountID' in df.columns and 'AccountNumber' in df.columns:
            exists = df[(df['AccountID'] == account_id) & (df['AccountNumber'] == account_number)]
            if not exists.empty:
                return False, "Beneficiary already exists"
            
        new_ben = {
            "AccountID": account_id,
            "BeneficiaryName": name,
            "AccountNumber": account_number,
            "IFSC": ifsc,
            "Nickname": nickname
        }
        
        df = pd.concat([df, pd.DataFrame([new_ben])], ignore_index=True)
        self._save_sheet(df, 'Beneficiaries')
        return True, "Beneficiary Added"

    def get_beneficiaries(self, account_id):
        df = self._load_sheet('Beneficiaries')
        if 'AccountID' not in df.columns: return []
        return df[df['AccountID'] == account_id].to_dict('records')

    # --- KYC ---
    def submit_kyc(self, account_id, doc_type, doc_number):
        df = self._load_sheet('KYCRequests')
        
        # Check if pending request exists
        pending = df[(df['AccountID'] == account_id) & (df['Status'] == 'Pending')]
        if not pending.empty:
            return False, "KYC Verification already in progress"
            
        new_request = {
            "RequestID": f"KYC-{len(df) + 1001}",
            "AccountID": account_id,
            "DocumentType": doc_type,
            "DocumentNumber": doc_number,
            "Status": "Pending",
            "SubmissionDate": datetime.now().strftime("%Y-%m-%d"),
            "AdminComments": ""
        }
        
        df = pd.concat([df, pd.DataFrame([new_request])], ignore_index=True)
        self._save_sheet(df, 'KYCRequests')
        
        # Update User Status to Pending
        users_df = self._load_sheet('Users')
        if account_id in users_df['AccountID'].values:
            idx = users_df[users_df['AccountID'] == account_id].index[0]
            users_df.at[idx, 'KYCStatus'] = 'Pending'
            self._save_sheet(users_df, 'Users')
            
        return True, "KYC Submitted"

    def get_kyc_status(self, account_id):
        df = self._load_sheet('Users')
        user = df[df['AccountID'] == account_id]
        if user.empty: return "Unknown"
        return user.iloc[0]['KYCStatus']

    def get_pending_kyc_requests(self):
        kyc_df = self._load_sheet('KYCRequests')
        users_df = self._load_sheet('Users')
        
        if 'RequestID' not in kyc_df.columns: return []
        
        pending_reqs = kyc_df[kyc_df['Status'] == 'Pending']
        
        results = []
        for _, req in pending_reqs.iterrows():
            acc_id = req['AccountID']
            user_match = users_df[users_df['AccountID'] == acc_id]
            full_name = user_match.iloc[0]['FullName'] if not user_match.empty else "Unknown User"
            
            results.append({
                "id": req['AccountID'],
                "request_id": req['RequestID'],
                "name": full_name,
                "docType": req['DocumentType'],
                "date": req['SubmissionDate'],
                "status": req['Status'],
                "docFile": "document_preview.jpg" # Mock filename for UI
            })
            
        return results

    def update_kyc_status(self, account_id, new_status):
        # 1. Update KYC Requests Sheet
        kyc_df = self._load_sheet('KYCRequests')
        if 'AccountID' in kyc_df.columns:
            # Update all pending for this user to new status
            indices = kyc_df[(kyc_df['AccountID'] == account_id) & (kyc_df['Status'] == 'Pending')].index
            for idx in indices:
                kyc_df.at[idx, 'Status'] = new_status
            self._save_sheet(kyc_df, 'KYCRequests')

        # 2. Update Users Sheet
        users_df = self._load_sheet('Users')
        if 'AccountID' in users_df.columns:
            idx = users_df[users_df['AccountID'] == account_id].index
            if not idx.empty:
                users_df.at[idx[0], 'KYCStatus'] = new_status
                self._save_sheet(users_df, 'Users')
                return True, f"KYC {new_status}"
                
        return False, "User not found"

    def update_user_status(self, account_id, new_status):
        users_df = self._load_sheet('Users')
        if 'AccountID' in users_df.columns:
            idx = users_df[users_df['AccountID'] == account_id].index
            if not idx.empty:
                users_df.at[idx[0], 'Status'] = new_status
                self._save_sheet(users_df, 'Users')
                return True, f"User status set to {new_status}"
        return False, "User not found"
