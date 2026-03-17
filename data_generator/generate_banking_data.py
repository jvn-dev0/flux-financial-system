import pandas as pd
import numpy as np
from faker import Faker
import random
import string
from datetime import datetime, timedelta

fake = Faker()

# Configuration
TOTAL_ROWS = 6500

# The user requested "mostly attack type data"
# So we will weight suspicious and compromised heavily.
NORMAL_PCT = 0.30
SUSPICIOUS_PCT = 0.40
COMPROMISED_PCT = 0.30

n_normal = int(TOTAL_ROWS * NORMAL_PCT)
n_suspicious = int(TOTAL_ROWS * SUSPICIOUS_PCT)
n_compromised = int(TOTAL_ROWS * COMPROMISED_PCT)
n_normal += TOTAL_ROWS - (n_normal + n_suspicious + n_compromised)

# 1. Generate a massive pool of realistic users
NUM_USERS = 800
users = []
print("Generating Users...")
for i in range(NUM_USERS):
    acct_id = f"AC{1001 + i}"
    users.append({
        "AccountID": acct_id,
        "Username": fake.user_name(),
        "Password": fake.password(length=12),
        "FullName": fake.name(),
        "Email": fake.email(),
        "Phone": fake.phone_number(),
        "AccountBalance": round(random.uniform(10.0, 95000.0), 2),
        "KYCStatus": random.choice(["Verified", "Verified", "Verified", "Pending", "Rejected"]),
        "CreatedAt": fake.date_time_between(start_date="-3y", end_date="-1m").strftime("%Y-%m-%d %H:%M:%S"),
        "AccountNumber": "".join(random.choices(string.digits, k=11)),
        "IFSC": f"FLUX0{fake.lexify(text='??????', letters=string.ascii_uppercase)}"
    })

# 2. Generator Logic combining User, Activity, and Target variables
def generate_row(user, risk_level):
    timestamp = fake.date_time_between(start_date="-1y", end_date="now")
    
    # Defaults (Normal)
    login_hour = timestamp.hour
    failed_logins = random.choice([0, 0, 0, 0, 1])
    new_device = 0
    password_changed = 0
    channel = random.choice(["Mobile", "Web", "Mobile"])
    pages_visited = random.randint(4, 15)
    click_rate = random.randint(3, 15)
    rapid_transactions = 0
    beneficiary_added = random.choice([0, 0, 0, 1])
    large_transaction = 0
    tx_amount = round(random.uniform(10.0, 2000.0), 2)
    device_trust = round(random.uniform(0.8, 1.0), 2)
    cyber_risk = random.randint(0, 25)
    risk_label = 0
    session_duration = random.randint(45, 900)
    tx_type = random.choice(["Credit", "Debit", "Transfer", "Login"])

    if risk_level == "Suspicious":
        # Elevated Risk (Probe / Setup)
        failed_logins = random.randint(2, 5)
        new_device = random.choice([0, 1])
        tx_amount = round(random.uniform(2000.0, 10000.0), 2)
        large_transaction = 1 if tx_amount > 5000 else 0
        device_trust = round(random.uniform(0.4, 0.7), 2)
        cyber_risk = random.randint(35, 65)
        risk_label = 1
        beneficiary_added = random.choice([0, 1, 1])
        login_hour = random.choice([0, 1, 2, 22, 23])
        rapid_transactions = random.choice([0, 1])
        session_duration = random.randint(15, 60)
    elif risk_level == "Compromised":
        # Definite Attack (Account Takeover / Looting)
        failed_logins = random.randint(5, 15)
        new_device = 1
        password_changed = random.choice([0, 1])
        tx_amount = round(random.uniform(10000.0, 95000.0), 2)
        large_transaction = 1
        device_trust = round(random.uniform(0.0, 0.3), 2)
        cyber_risk = random.randint(75, 100)
        risk_label = 1
        beneficiary_added = 1
        rapid_transactions = 1
        login_hour = random.choice([0, 1, 2, 3])
        session_duration = random.randint(5, 20) # In and out quickly to drain funds
        channel = "Web"
        tx_type = "Transfer"
    
    return {
        "LogID": "LOG-" + fake.uuid4()[:8],
        
        # User Columns
        "Username": user["Username"],
        "Password": user["Password"],
        "FullName": user["FullName"],
        "Email": user["Email"],
        "Phone": user["Phone"],
        "AccountBalance": user["AccountBalance"],
        "KYCStatus": user["KYCStatus"],
        "CreatedAt": user["CreatedAt"],
        "AccountNumber": user["AccountNumber"],
        "IFSC": user["IFSC"],
        "AccountID": user["AccountID"],
        
        # ActivityLogs Columns + ML metrics
        "Timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "TransactionType": tx_type,
        "Description": fake.sentence(nb_words=4)[:-1], # Remove trailing dot
        "SessionID": "SES-" + fake.uuid4()[:8],
        "TransactionAmount": tx_amount,
        "SessionDuration": session_duration,
        "LoginHour": login_hour,
        "FailedLoginCount": failed_logins,
        "NewDeviceLogin": new_device,
        "PasswordChanged": password_changed,
        "Channel": channel,
        "PagesVisited": pages_visited,
        "ClickRate": click_rate,
        "RapidTransactions": rapid_transactions,
        "BeneficiaryAdded": beneficiary_added,
        "LargeTransaction": large_transaction,
        "DeviceTrustScore": device_trust,
        "CyberRiskScore": cyber_risk,
        "RiskLabel": risk_label,
        
        # Beneficiary
        "BeneficiaryName": fake.name() if beneficiary_added else "None"
    }

data = []
print("Generating Transaction Logs...")
for _ in range(n_normal):
    data.append(generate_row(random.choice(users), "Normal"))
for _ in range(n_suspicious):
    data.append(generate_row(random.choice(users), "Suspicious"))
for _ in range(n_compromised):
    data.append(generate_row(random.choice(users), "Compromised"))

# 3. Create DataFrame and Shuffle
df = pd.DataFrame(data)
df = df.sample(frac=1).reset_index(drop=True)

# 4. Save to CSV without any nulls
output_path = "banking_activity_logs.csv"
df.to_csv(output_path, index=False)

print(f"\n--- SUCCESS ---")
print(f"Generated a massive 0-null CSV dataset of {len(df)} rows.")
print("Risk Label Distribution (1 = Attack, 0 = Normal):")
print(df['RiskLabel'].value_counts())
print(f"\nSaved directly to: {output_path}")
