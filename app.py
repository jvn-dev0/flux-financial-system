import sys
import os

# Render's explicit dashboard setting forces Gunicorn to look for 'app:app' at the root level.
# By inserting the 'bank' directory into the system path, we allow bank/app.py to
# cleanly import local modules (like database_manager) without crashing.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bank'))

# Import the actual Flask application object from the bank subsystem
from bank.app import app

if __name__ == '__main__':
    app.run()
