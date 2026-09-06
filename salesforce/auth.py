"""Salesforce OAuth: token exchange, local callback server, token persistence."""

import base64
import hashlib
import http.server
import json
import logging
import os
from pathlib import Path
import secrets
import socketserver
import threading
import time
from urllib.parse import parse_qs, urlparse
import requests

from config import settings

logger = logging.getLogger(__name__)


# ==================================================
# ==================================================
# ENVIRONMENT PROFILES
# ==================================================

def get_active_profile() -> str:
    """Get current active Salesforce environment profile ('sandbox' or 'prod')."""
    if settings.PROFILE_FILE.exists():
        try:
            with open(settings.PROFILE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                prof = data.get("active_profile", settings.DEFAULT_PROFILE)
                if prof in settings.PROFILES:
                    return prof
        except Exception as e:
            logger.warning("Could not read profile file, using default: %s", e)
    return settings.DEFAULT_PROFILE


def set_active_profile(profile: str) -> None:
    """Set current active Salesforce environment profile."""
    if profile not in settings.PROFILES:
        raise ValueError(f"Unknown profile: {profile}. Expected one of {list(settings.PROFILES.keys())}")
    try:
        with open(settings.PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump({"active_profile": profile}, f, indent=2)
        logger.info("Active Salesforce profile set to: %s", profile)
        invalidate_connection_cache()
    except Exception as e:
        logger.error("Failed to save active profile: %s", e)


def get_token_file(profile: str | None = None) -> Path:
    """Get the token file path for a given profile (or active profile if None)."""
    prof = profile or get_active_profile()
    return settings.PROJECT_ROOT / f".sf_auth_{prof}.json"


def sanitize_session_token(token_raw: str) -> str:
    """Clean session token by stripping whitespace, 'MY_TOKEN:', and '###' separators."""
    if not token_raw:
        return ""
    clean = token_raw.strip()
    if "MY_TOKEN:" in clean:
        clean = clean.split("MY_TOKEN:")[1].strip()
    clean = clean.replace("###", "").strip().strip('"').strip("'")
    return clean


# ==================================================
# CREDENTIALS CONFIGURATION
# ==================================================

def is_oauth_configured() -> bool:
    """Check if Client ID and Secret are configured."""
    return bool(settings.SF_CLIENT_ID and settings.SF_CLIENT_SECRET)


def save_env_credentials(
    client_id: str,
    client_secret: str,
    login_url: str = "https://test.salesforce.com",
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


PKCE_FILE = settings.PROJECT_ROOT / ".sf_pkce.json"


def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (RFC 7636)."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def save_pkce_session(
    verifier: str,
    client_id: str = "",
    client_secret: str = "",
    login_url: str = "",
    profile: str | None = None
) -> str:
    """Save PKCE session keyed by unique state token."""
    state = secrets.token_urlsafe(24)
    prof = profile or get_active_profile()
    try:
        data = {}
        if PKCE_FILE.exists():
            try:
                with open(PKCE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data[state] = {
            "verifier": verifier,
            "client_id": client_id,
            "client_secret": client_secret,
            "login_url": login_url,
            "profile": prof,
            "created_at": time.time(),
        }
        # Backward compatibility fallback
        data[prof] = data[state]
        with open(PKCE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("Could not persist PKCE session: %s", e)
    return state


def sanitize_consumer_key(key: str) -> str:
    """Clean and sanitize Consumer Key input, correcting common mobile copy-paste truncations."""
    clean = (key or "").strip().strip("'\"")
    # If user missed the leading '3' during selection (e.g. 'MVG9...')
    if clean.startswith("MVG9") and len(clean) == 84:
        clean = "3" + clean
    # If character 57 was transcribed as lowercase 'l' instead of uppercase 'I'
    if len(clean) == 85 and clean.startswith("3MVG93BtyJZJrcZ6qrxUJ0_y2UH85laQHifPV81Bp1pOs3ItYbyoy_X5n"):
        if clean[57] == "l":
            clean = clean[:57] + "I" + clean[58:]
    return clean


def pop_pkce_session(state: str | None = None, profile: str | None = None) -> dict:
    """Retrieve and remove stored PKCE session by state (with robust fallback to profile or newest)."""
    prof = profile or get_active_profile()
    if not PKCE_FILE.exists():
        return {}
    try:
        with open(PKCE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        session_info = {}
        if state and state in data and isinstance(data[state], dict):
            session_info = data.pop(state)
        elif prof in data:
            val = data.pop(prof)
            if isinstance(val, dict):
                session_info = val
            else:
                session_info = {"verifier": val}
        elif data:
            # Fallback: find the newest valid session
            newest_key = None
            newest_time = 0
            for k, v in data.items():
                if isinstance(v, dict) and "verifier" in v:
                    t = v.get("created_at", 0)
                    if t >= newest_time:
                        newest_time = t
                        newest_key = k
            if newest_key:
                session_info = data.pop(newest_key)

        with open(PKCE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return session_info
    except Exception as e:
        logger.warning("Could not pop PKCE session: %s", e)
        return {}


def save_code_verifier(verifier: str, profile: str | None = None) -> None:
    """Save code verifier to match callback code exchange (legacy compatibility)."""
    save_pkce_session(verifier, profile=profile)


def pop_code_verifier(profile: str | None = None) -> str | None:
    """Retrieve and remove stored PKCE code verifier (legacy compatibility)."""
    sess = pop_pkce_session(profile=profile)
    return sess.get("verifier")


def get_login_url(
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    login_url: str | None = None,
    profile: str | None = None
) -> str:
    """Generate the OAuth 2.0 authorization URL with PKCE and state tracking (RFC 7636)."""
    prof = profile or get_active_profile()
    base_url = (login_url or settings.SF_LOGIN_URL).strip().rstrip("/")
    if prof == "sandbox" and "login.salesforce.com" in base_url:
        base_url = "https://test.salesforce.com"
    elif prof == "prod" and "test.salesforce.com" in base_url:
        base_url = "https://login.salesforce.com"

    cid = sanitize_consumer_key(client_id or settings.SF_CLIENT_ID)
    csec = (client_secret or settings.SF_CLIENT_SECRET).strip().strip("'\"")
    r_uri = (redirect_uri or settings.SF_REDIRECT_URI).strip()

    verifier, challenge = generate_pkce_pair()
    state = save_pkce_session(verifier, client_id=cid, client_secret=csec, login_url=base_url, profile=prof)

    return (
        f"{base_url}/services/oauth2/authorize"
        f"?response_type=code"
        f"&client_id={cid}"
        f"&redirect_uri={r_uri}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
        f"&state={state}"
    )


# ==================================================
# TOKEN STORE
# ==================================================

# In-memory cache for live connection checks: profile -> (timestamp, is_connected, status_message)
_CONNECTION_STATUS_CACHE: dict[str, tuple[float, bool, str]] = {}


def invalidate_connection_cache(profile: str | None = None) -> None:
    """Clear cached connection status for a profile or all profiles."""
    if profile:
        _CONNECTION_STATUS_CACHE.pop(profile, None)
    else:
        _CONNECTION_STATUS_CACHE.clear()


def save_token(token_data: dict, profile: str | None = None) -> None:
    """Save Salesforce OAuth token locally for specified profile."""
    prof = profile or get_active_profile()
    if "issued_at" not in token_data:
        token_data["saved_at"] = time.time()

    token_path = get_token_file(prof)
    with open(token_path, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)

    invalidate_connection_cache(prof)
    logger.info("Saved Salesforce token to %s", token_path.name)


def save_manual_token(access_token: str, instance_url: str, profile: str | None = None) -> None:
    """Save manually provided access token and instance URL, automatically sanitizing token input."""
    prof = profile or get_active_profile()
    clean_token = sanitize_session_token(access_token)
    clean_url = instance_url.strip().rstrip("/")
    token_data = {
        "access_token": clean_token,
        "instance_url": clean_url,
        "token_type": "Bearer",
        "saved_at": time.time(),
        "profile": prof
    }
    save_token(token_data, profile=prof)


def load_token(profile: str | None = None) -> dict | None:
    """Load stored Salesforce token if exists for the profile."""
    prof = profile or get_active_profile()
    token_path = get_token_file(prof)
    if not token_path.exists():
        legacy_file = settings.PROJECT_ROOT / ".sf_auth.json"
        if prof == settings.DEFAULT_PROFILE and legacy_file.exists():
            token_path = legacy_file
        else:
            return None

    try:
        with open(token_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Failed to read token file %s: %s", token_path, e)
        return None


def clear_token(profile: str | None = None) -> None:
    """Logout / clear stored token for specified profile."""
    prof = profile or get_active_profile()
    token_path = get_token_file(prof)
    if token_path.exists():
        try:
            os.remove(token_path)
            logger.info("Cleared Salesforce token: %s", token_path.name)
        except Exception as e:
            logger.error("Failed to delete token file: %s", e)

    legacy_file = settings.PROJECT_ROOT / ".sf_auth.json"
    if prof == settings.DEFAULT_PROFILE and legacy_file.exists():
        try:
            os.remove(legacy_file)
        except Exception:
            pass

    invalidate_connection_cache(prof)


def clear_saved_credentials() -> None:
    """Clear saved credentials in .env and runtime settings."""
    settings.SF_CLIENT_ID = ""
    settings.SF_CLIENT_SECRET = ""
    env_file = settings.PROJECT_ROOT / ".env"
    if env_file.exists():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                if line.startswith("SF_CLIENT_ID="):
                    new_lines.append("SF_CLIENT_ID=\n")
                elif line.startswith("SF_CLIENT_SECRET="):
                    new_lines.append("SF_CLIENT_SECRET=\n")
                else:
                    new_lines.append(line)
            with open(env_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            logger.info("Cleared saved credentials from .env")
        except Exception as e:
            logger.error("Failed to clear credentials from .env: %s", e)


def is_token_valid(profile: str | None = None, check_live: bool = False) -> bool:
    """Check if stored token exists and hasn't expired."""
    if check_live:
        is_conn, _ = check_connection_status(profile=profile)
        return is_conn

    token = load_token(profile)
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


def check_connection_status(
    profile: str | None = None,
    force_check: bool = False,
    timeout: float = 2.5
) -> tuple[bool, str]:
    """
    Dynamically verify Salesforce connection status.

    Returns:
        tuple: (is_connected: bool, status_label: str)
        status_label can be 'Connected', 'Disconnected', 'Session Expired', or 'Offline'.
    """
    prof = profile or get_active_profile()

    # 1. Fast disk check
    token = load_token(prof)
    if not token or "access_token" not in token or not str(token.get("access_token", "")).strip():
        invalidate_connection_cache(prof)
        return False, "Disconnected"

    instance_url = token.get("instance_url", "").strip().rstrip("/")
    if not instance_url:
        invalidate_connection_cache(prof)
        return False, "Disconnected"

    # 2. Check cached result (TTL: 30 seconds)
    now = time.time()
    if not force_check and prof in _CONNECTION_STATUS_CACHE:
        cached_time, cached_ok, cached_msg = _CONNECTION_STATUS_CACHE[prof]
        if now - cached_time < 30.0:
            return cached_ok, cached_msg

    # 3. Arithmetic timestamp expiration check
    issued_at = token.get("issued_at")
    saved_at = token.get("saved_at")
    is_timestamp_expired = False
    if issued_at:
        try:
            if now - (int(issued_at) / 1000) > 7000:
                is_timestamp_expired = True
        except (ValueError, TypeError):
            pass
    elif saved_at:
        try:
            if now - float(saved_at) > 7000:
                is_timestamp_expired = True
        except (ValueError, TypeError):
            pass

    if is_timestamp_expired:
        refresh_tok = token.get("refresh_token")
        if refresh_tok and settings.SF_CLIENT_ID and settings.SF_CLIENT_SECRET:
            try:
                logger.info("Token expired by timestamp. Attempting auto-refresh for %s...", prof)
                token = refresh_access_token(refresh_tok, profile=prof)
            except Exception as e:
                logger.warning("Auto-refresh failed during connection check: %s", e)
                _CONNECTION_STATUS_CACHE[prof] = (now, False, "Session Expired")
                return False, "Session Expired"
        else:
            _CONNECTION_STATUS_CACHE[prof] = (now, False, "Session Expired")
            return False, "Session Expired"

    # 4. Fast live ping to Salesforce userinfo endpoint
    headers = {
        "Authorization": f"Bearer {token['access_token']}",
        "Content-Type": "application/json"
    }
    userinfo_url = f"{instance_url}/services/oauth2/userinfo"
    try:
        resp = requests.get(userinfo_url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            _CONNECTION_STATUS_CACHE[prof] = (now, True, "Connected")
            return True, "Connected"
        elif resp.status_code in (401, 403):
            # Attempt auto-refresh if refresh token is present
            refresh_tok = token.get("refresh_token")
            if refresh_tok and settings.SF_CLIENT_ID and settings.SF_CLIENT_SECRET:
                try:
                    logger.info("Session returned %s. Attempting auto-refresh for %s...", resp.status_code, prof)
                    new_token = refresh_access_token(refresh_tok, profile=prof)
                    headers["Authorization"] = f"Bearer {new_token['access_token']}"
                    resp2 = requests.get(userinfo_url, headers=headers, timeout=timeout)
                    if resp2.status_code == 200:
                        _CONNECTION_STATUS_CACHE[prof] = (now, True, "Connected")
                        return True, "Connected"
                except Exception as ref_err:
                    logger.warning("Token refresh failed: %s", ref_err)

            _CONNECTION_STATUS_CACHE[prof] = (now, False, "Session Expired")
            return False, "Session Expired"
        else:
            logger.warning("Salesforce userinfo check returned HTTP %s", resp.status_code)
            _CONNECTION_STATUS_CACHE[prof] = (now, False, "Offline")
            return False, "Offline"
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
        logger.warning("Network connection check failed for %s: %s", prof, net_err)
        _CONNECTION_STATUS_CACHE[prof] = (now, False, "Offline")
        return False, "Offline"
    except Exception as e:
        logger.warning("Unexpected error during connection check: %s", e)
        _CONNECTION_STATUS_CACHE[prof] = (now, False, "Offline")
        return False, "Offline"



# ==================================================
# OAUTH CLIENT
# ==================================================

def exchange_code_for_token(
    auth_code: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
    login_url: str | None = None,
    code_verifier: str | None = None,
    profile: str | None = None
) -> dict:
    """Exchange OAuth authorization code for access token."""
    cid = sanitize_consumer_key(client_id or settings.SF_CLIENT_ID)
    csec = (client_secret or settings.SF_CLIENT_SECRET).strip().strip("'\"")
    r_uri = (redirect_uri or settings.SF_REDIRECT_URI).strip()

    if not all([cid, csec, r_uri]):
        raise RuntimeError("Missing Salesforce OAuth configuration (Client ID, Secret, or Redirect URI)")

    prof = profile or get_active_profile()
    base_url = (login_url or settings.SF_LOGIN_URL).strip().rstrip("/")
    if prof == "sandbox" and "login.salesforce.com" in base_url:
        base_url = "https://test.salesforce.com"
    elif prof == "prod" and "test.salesforce.com" in base_url:
        base_url = "https://login.salesforce.com"

    token_url = f"{base_url}/services/oauth2/token"

    payload = {
        "grant_type": "authorization_code",
        "code": auth_code.strip(),
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": r_uri,
    }

    verifier = code_verifier or pop_code_verifier(prof) or pop_pkce_session(profile=prof).get("verifier")
    if verifier:
        payload["code_verifier"] = verifier

    response = requests.post(token_url, data=payload)

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to get token ({response.status_code}): {response.text}"
        )

    token_data = response.json()
    token_data["profile"] = prof
    save_token(token_data, profile=prof)
    return token_data


def refresh_access_token(refresh_token_str: str, profile: str | None = None) -> dict:
    """Exchange a stored refresh token for a fresh access token."""
    if not settings.SF_CLIENT_ID or not settings.SF_CLIENT_SECRET:
        raise RuntimeError("Missing Salesforce Client ID or Secret in settings or .env")

    prof = profile or get_active_profile()
    base_url = settings.SF_LOGIN_URL
    if prof == "sandbox" and "login.salesforce.com" in base_url:
        base_url = "https://test.salesforce.com"
    elif prof == "prod" and "test.salesforce.com" in base_url:
        base_url = "https://login.salesforce.com"

    token_url = f"{base_url}/services/oauth2/token"
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

    existing = load_token(profile=prof)
    if existing and "instance_url" in existing and "instance_url" not in new_data:
        new_data["instance_url"] = existing["instance_url"]

    new_data["profile"] = prof
    save_token(new_data, profile=prof)
    logger.info("Successfully refreshed Salesforce access token for profile '%s'", prof)
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
        state = query.get("state")
        state_val = state[0] if state else None

        if not auth_code:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing auth code")
            return

        auth_code = auth_code[0]

        try:
            prof = get_active_profile()
            sess = pop_pkce_session(state=state_val, profile=prof)
            cid = sess.get("client_id") or settings.SF_CLIENT_ID
            csec = sess.get("client_secret") or settings.SF_CLIENT_SECRET
            lurl = sess.get("login_url") or settings.SF_LOGIN_URL
            session_prof = sess.get("profile") or prof
            ver = sess.get("verifier")

            token_data = exchange_code_for_token(
                auth_code,
                client_id=cid,
                client_secret=csec,
                login_url=lurl,
                code_verifier=ver,
                profile=session_prof
            )
            save_token(token_data, profile=session_prof)

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
