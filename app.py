import sys
import os

# Add bank folder to path so internal imports like 'database_manager' work
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bank'))

from app import app

if __name__ == '__main__':
    app.run()
