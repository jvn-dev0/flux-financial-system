import pandas as pd
from database_manager import DatabaseManager

db = DatabaseManager()
df = db._load_sheet('ML_Features')
print("Columns:", df.columns.tolist())
try:
    print("Does AccountID exist?", 'AccountID' in df.columns)
except Exception as e:
    print(e)
