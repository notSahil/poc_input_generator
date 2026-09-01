"""Central application settings. Single source of truth for all config."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# === Paths ===
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
COMMON_DIR = DATA_DIR / "common"
MAPPING_FILE = COMMON_DIR / "Mapping_file.xlsx"
MAPPING_HISTORY_DIR = COMMON_DIR / "mapping_history"
CONFIG_DIR = PROJECT_ROOT / "config" / "reports"

# === Salesforce OAuth ===
SF_CLIENT_ID = os.getenv("SF_CLIENT_ID", "")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET", "")
SF_REDIRECT_URI = os.getenv("SF_REDIRECT_URI", "http://localhost:1717/oauth/callback")
SF_LOGIN_URL = os.getenv("SF_LOGIN_URL", "https://login.salesforce.com")
SF_API_VERSION = os.getenv("SF_API_VERSION", "v59.0")

# === Server ===
OAUTH_CALLBACK_PORT = int(os.getenv("OAUTH_CALLBACK_PORT", "1717"))

# === Token ===
TOKEN_FILE = PROJECT_ROOT / ".sf_auth.json"
