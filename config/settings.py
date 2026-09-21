"""Central application settings. Single source of truth for all config."""

import os
from pathlib import Path
from dotenv import load_dotenv

def reload_settings():
    """Reload settings from .env file, updating all module globals."""
    load_dotenv(override=True)
    global SF_CLIENT_ID, SF_CLIENT_SECRET, SF_REDIRECT_URI, SF_LOGIN_URL, SF_API_VERSION, OAUTH_CALLBACK_PORT
    global SCHEDULER_TIMEZONE, SCHEDULER_POLL_INTERVAL_SECONDS, SCHEDULER_MAX_RETRIES
    global SCHEDULER_EXECUTION_TIMEOUT_MINUTES, ALLOW_SCHEDULED_PROD_PUSH
    global SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_USE_TLS, SMTP_SENDER
    global NOTIFICATION_EMAILS, SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL

    SF_CLIENT_ID = os.getenv("SF_CLIENT_ID", "")
    SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET", "")
    SF_REDIRECT_URI = os.getenv("SF_REDIRECT_URI", "http://localhost:1717/oauth/callback")
    SF_LOGIN_URL = os.getenv("SF_LOGIN_URL", "https://test.salesforce.com")
    SF_API_VERSION = os.getenv("SF_API_VERSION", "v59.0")
    OAUTH_CALLBACK_PORT = int(os.getenv("OAUTH_CALLBACK_PORT", "1717"))

    SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Europe/London")
    SCHEDULER_POLL_INTERVAL_SECONDS = int(os.getenv("SCHEDULER_POLL_INTERVAL", "60"))
    SCHEDULER_MAX_RETRIES = int(os.getenv("SCHEDULER_MAX_RETRIES", "3"))
    SCHEDULER_EXECUTION_TIMEOUT_MINUTES = int(os.getenv("SCHEDULER_EXECUTION_TIMEOUT", "30"))
    ALLOW_SCHEDULED_PROD_PUSH = os.getenv("ALLOW_SCHEDULED_PROD_PUSH", "true").lower() == "true"

    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    SMTP_SENDER = os.getenv("SMTP_SENDER", "sitetracker-datahub@company.com")
    NOTIFICATION_EMAILS = [e.strip() for e in os.getenv("NOTIFICATION_EMAILS", "").split(",") if e.strip()]

    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
    TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")


load_dotenv(override=True)

# === Paths ===
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
COMMON_DIR = DATA_DIR / "common"
MAPPING_FILE = COMMON_DIR / "Mapping_file.xlsx"
MAPPING_HISTORY_DIR = COMMON_DIR / "mapping_history"
MAPPING_PROFILES_DIR = DATA_DIR / "mapping_profiles"
CONFIG_DIR = PROJECT_ROOT / "config" / "reports"

# === Persistent Job Queue ===
JOBS_DB_PATH: Path = DATA_DIR / "jobs.db"

# === Scheduler Settings ===
SCHEDULER_TIMEZONE: str = os.getenv("SCHEDULER_TIMEZONE", "Europe/London")
SCHEDULER_POLL_INTERVAL_SECONDS: int = int(os.getenv("SCHEDULER_POLL_INTERVAL", "60"))
SCHEDULER_MAX_RETRIES: int = int(os.getenv("SCHEDULER_MAX_RETRIES", "3"))
SCHEDULER_EXECUTION_TIMEOUT_MINUTES: int = int(os.getenv("SCHEDULER_EXECUTION_TIMEOUT", "30"))
ALLOW_SCHEDULED_PROD_PUSH: bool = os.getenv("ALLOW_SCHEDULED_PROD_PUSH", "true").lower() == "true"

# === Email Notifications (SMTP) ===
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
SMTP_SENDER: str = os.getenv("SMTP_SENDER", "sitetracker-datahub@company.com")
NOTIFICATION_EMAILS: list[str] = [
    e.strip() for e in os.getenv("NOTIFICATION_EMAILS", "").split(",") if e.strip()
]

# === Webhook Notifications ===
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")
TEAMS_WEBHOOK_URL: str = os.getenv("TEAMS_WEBHOOK_URL", "")

# === Salesforce OAuth ===
SF_CLIENT_ID = os.getenv("SF_CLIENT_ID", "")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET", "")
SF_REDIRECT_URI = os.getenv("SF_REDIRECT_URI", "http://localhost:1717/oauth/callback")
SF_LOGIN_URL = os.getenv("SF_LOGIN_URL", "https://test.salesforce.com")
SF_API_VERSION = os.getenv("SF_API_VERSION", "v59.0")

# === Server ===
OAUTH_CALLBACK_PORT = int(os.getenv("OAUTH_CALLBACK_PORT", "1717"))

# === Token & Environment Profiles ===
PROFILE_FILE = PROJECT_ROOT / ".sf_profile.json"
DEFAULT_PROFILE = "sandbox"
PROFILES = {
    "sandbox": "🧪 Sitetracker Developer Sandbox",
    "partial": "🔬 Sitetracker Partial Copy Sandbox",
    "prod": "🏢 Sitetracker Production (Live)"
}
TOKEN_FILE = PROJECT_ROOT / ".sf_auth.json"
