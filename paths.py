import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Centralized resource paths (relative to BASE_DIR)
TOKEN_FILE_PATH = os.path.join(BASE_DIR, "tokens.txt")
LOG_FILE_PATH = os.path.join(BASE_DIR, "fyers_auth_log.txt")
# Add event log directory (used in event_log.py)
EVENT_LOG_DIR = os.path.join(BASE_DIR, "event_logs")