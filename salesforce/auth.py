"""Salesforce OAuth: token exchange, local callback server, token persistence."""

import http.server
import json
import logging
import os
import socketserver
import threading
import time
from urllib.parse import parse_qs, urlparse
import requests

from config import settings

logger = logging.getLogger(__name__)


# ==================================================
# TOKEN STORE
# ==================================================

def save_token(token_data: dict) -> None:
    """
    Save Salesforce OAuth token locally.
    This file must NEVER be committed to git.
    """
    # Record issued timestamp if not present
    if "issued_at" not in token_data:
        token_data["saved_at"] = time.time()
        
    with open(settings.TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)
    logger.info("Saved Salesforce OAuth token")


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

    # Check expiration if timestamp available (Salesforce tokens typically expire in ~2h)
    issued_at = token.get("issued_at")
    saved_at = token.get("saved_at")
    
    if issued_at:
        try:
            issued_ts = int(issued_at) / 1000  # ms to seconds
            if time.time() - issued_ts > 7000:  # ~2 hours with buffer
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
        raise RuntimeError("Missing Salesforce OAuth environment variables in settings or .env")

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
                b"Salesforce login successful. You may close this window."
            )

            # Stop server after success in a background thread
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        except Exception as e:
            logger.error("OAuth exchange failed: %s", e)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, format, *args):
        # Suppress default noisy HTTP request logging
        logger.debug("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), format % args))


def start_oauth_server(port: int = settings.OAUTH_CALLBACK_PORT) -> None:
    """Start local OAuth callback server."""
    logger.info("Starting local OAuth callback server on port %s", port)
    # Allow address reuse to prevent bind error on quick restarts
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("localhost", port), OAuthHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        logger.error("OAuth server error: %s", e)
