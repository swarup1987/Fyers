# config.py

import os
from datetime import datetime

# Fyers API Configuration
CLIENT_ID = "8CT51FCC5R-100"
SECRET_KEY = "CSFUO4A3IY"
REDIRECT_URI = "http://localhost:8000"
RESPONSE_TYPE = "code"
GRANT_TYPE = "authorization_code"

# Token Management
access_token = None
refresh_token = None

def set_tokens(access, refresh):
    global access_token, refresh_token
    access_token = access
    refresh_token = refresh

def get_tokens():
    return access_token, refresh_token

def save_tokens_to_file(access, refresh):
    save_dir = os.path.expanduser("~/Desktop/daily_token")
    os.makedirs(save_dir, exist_ok=True)
    filename = f"tokens_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
    with open(os.path.join(save_dir, filename), 'w') as f:
        f.write(f"Access Token: {access}\n")
        f.write(f"Refresh Token: {refresh}\n")

def load_latest_token_from_file():
    folder = os.path.expanduser("~/Desktop/daily_token")
    if not os.path.exists(folder):
        return None

    files = [f for f in os.listdir(folder) if f.startswith("tokens_") and f.endswith(".txt")]
    if not files:
        return None

    # Sort by creation time, pick most recent
    latest_file = max(files, key=lambda f: os.path.getctime(os.path.join(folder, f)))
    with open(os.path.join(folder, latest_file), 'r') as f:
        lines = f.readlines()
        access = lines[0].split(":", 1)[-1].strip()
        refresh = lines[1].split(":", 1)[-1].strip()
        return access, refresh
