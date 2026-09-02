"""Salesforce OAuth: token exchange, local callback server, token persistence."""

import http.server
import json
import logging
import os
from pathlib import Path
import socketserver
import threading
import time
from urllib.parse import parse_qs, urlparse
import requests

from config import settings

logger = logging.getLogger(__name__)


# ==================================================
# CREDENTIALS CONFIGURATION
# ==================================================

def is_oauth_configured() -> bool:
    """Check if Client ID and Secret are configured."""
    return bool(settings.SF_CLIENT_ID and settings.SF_CLIENT_SECRET)


def save_env_credentials(
    client_id: str,
    client_secret: str,
    login_url: str = "https://login.salesforce.com",
    redirect_uri: str = "http://localhost:1717/oauth/callback"
) -> None:
    """Save credentials to .env file and update settings in memory."""
    env_file = settings.PROJECT_ROOT / ".env"

    env_lines = [
        f"SF_CLIENT_ID={client_id.strip()}",
        f"SF_CLIENT_SECRET={client_secret.strip()}",
        f"SF_LOGIN_URL={login_url.strip()}",
        f"SF_REDIRECT_URI={redirect_uri.strip()}",
        f"SF_API_VERSION={settings.SF_API_VERSION}",
        f"OAUTH_CALLBACK_PORT={settings.OAUTH_CALLBACK_PORT}",
    ]

    with open(env_file, "w", encoding="utf-8") as f:
        f.write("\n".join(env_lines) + "\n")

    # Update runtime settings
    settings.SF_CLIENT_ID = client_id.strip()
    settings.SF_CLIENT_SECRET = client_secret.strip()
    settings.SF_LOGIN_URL = login_url.strip()
    settings.SF_REDIRECT_URI = redirect_uri.strip()

    logger.info("Saved Salesforce credentials to .env")


def get_login_url() -> str:
    """Generate the OAuth 2.0 authorization URL."""
    return (
        f"{settings.SF_LOGIN_URL}/services/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={settings.SF_CLIENT_ID}"
        f"&redirect_uri={settings.SF_REDIRECT_URI}"
    )


# ==================================================
# TOKEN STORE
# ==================================================

def save_token(token_data: dict) -> None:
    """Save Salesforce OAuth token locally."""
    if "issued_at" not in token_data:
        token_data["saved_at"] = time.time()

    with open(settings.TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    logger.info("Saved Salesforce OAuth token")


def save_manual_token(access_token: str, instance_url: str) -> None:
    """Save manually provided access token and instance URL."""
    token_data = {
        "access_token": access_token.strip(),
        "instance_url": instance_url.strip().rstrip("/"),
        "token_type": "Bearer",
        "saved_at": time.time()
    }
    save_token(token_data)


def load_token() -> dict | None:
    """Load stored Salesforce token if exists."""
    if not settings.TOKEN_FILE.exists():
        return None

    try:
        with open(settings.TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to read token file: %s", e)
        return None


def clear_token() -> None:
    """Logout / clear stored token."""
    if settings.TOKEN_FILE.exists():
        try:
            os.remove(settings.TOKEN_FILE)
            logger.info("Cleared Salesforce token")
        except Exception as e:
            logger.error("Failed to delete token file: %s", e)


def is_token_valid() -> bool:
    """Check if stored token exists and hasn't expired."""
    token = load_token()
    if not token or "access_token" not in token:
        return False

    issued_at = token.get("issued_at")
    saved_at = token.get("saved_at")

    if issued_at:
        try:
            issued_ts = int(issued_at) / 1000
            if time.time() - issued_ts > 7000:
                return False
        except (ValueError, TypeError):
            pass
    elif saved_at:
        if time.time() - float(saved_at) > 7000:
            return False

    return True


# ==================================================
# OAUTH CLIENT
# ==================================================

def exchange_code_for_token(auth_code: str) -> dict:
    """Exchange OAuth authorization code for access token."""
    if not all([settings.SF_CLIENT_ID, settings.SF_CLIENT_SECRET, settings.SF_REDIRECT_URI, settings.SF_LOGIN_URL]):
        raise RuntimeError("Missing Salesforce OAuth configuration in settings or .env")

    token_url = f"{settings.SF_LOGIN_URL}/services/oauth2/token"

    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": settings.SF_CLIENT_ID,
        "client_secret": settings.SF_CLIENT_SECRET,
        "redirect_uri": settings.SF_REDIRECT_URI,
    }

    response = requests.post(token_url, data=payload)

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to get token: {response.status_code} - {response.text}"
        )

    return response.json()


def refresh_access_token(refresh_token_str: str) -> dict:
    """Exchange a stored refresh token for a fresh access token."""
    if not settings.SF_CLIENT_ID or not settings.SF_CLIENT_SECRET:
        raise RuntimeError("Missing Salesforce Client ID or Secret in settings or .env")

    token_url = f"{settings.SF_LOGIN_URL}/services/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.SF_CLIENT_ID,
        "client_secret": settings.SF_CLIENT_SECRET,
        "refresh_token": refresh_token_str.strip(),
    }

    response = requests.post(token_url, data=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Token refresh failed ({response.status_code}): {response.text}")

    new_data = response.json()
    # If rotation not enabled, preserve original refresh token
    if "refresh_token" not in new_data:
        new_data["refresh_token"] = refresh_token_str.strip()

    existing = load_token()
    if existing and "instance_url" in existing and "instance_url" not in new_data:
        new_data["instance_url"] = existing["instance_url"]

    save_token(new_data)
    logger.info("Successfully refreshed Salesforce access token")
    return new_data


# ==================================================
# OAUTH CALLBACK SERVER
# ==================================================

class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/oauth/callback":
            self.send_response(404)
            self.end_headers()
            return

        query = parse_qs(parsed.query)
        auth_code = query.get("code")

        if not auth_code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing auth code")
            return

        auth_code = auth_code[0]

        try:
            token_data = exchange_code_for_token(auth_code)
            save_token(token_data)

            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family: sans-serif; text-align: center; padding: 50px;'>"
                b"<h2 style='color: #2e7d32;'>&#10004; Salesforce Login Successful!</h2>"
                b"<p>You can close this tab and return to the Sitetracker Data Hub.</p>"
                b"</body></html>"
            )

            # Stop server after success in a background thread
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        except Exception as e:
            logger.error("OAuth exchange failed: %s", e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        logger.debug("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))


def start_oauth_server(port: int = settings.OAUTH_CALLBACK_PORT) -> None:
    """Start local OAuth callback server."""
    logger.info("Starting local OAuth callback server on port %s", port)
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("localhost", port), OAuthHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        logger.warning("OAuth server exception (may already be running): %s", e)
