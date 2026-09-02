"""Bridge: Create a simple-salesforce Salesforce instance from stored OAuth token."""

import logging
from simple_salesforce import Salesforce

from core.exceptions import SalesforceAuthError
from salesforce.auth import is_token_valid, load_token, refresh_access_token

logger = logging.getLogger(__name__)


def get_sf_connection() -> Salesforce:
    """
    Return a ready-to-use simple-salesforce Salesforce instance
    using the existing OAuth token from .sf_auth.json.
    Automatically attempts token refresh if the access token has expired.

    Raises:
        SalesforceAuthError: If user is not authenticated or token refresh fails.
    """
    token = load_token()
    if not token or "access_token" not in token:
        raise SalesforceAuthError("No valid Salesforce token found. Please login first.")

    # Check validity and attempt auto-refresh if needed
    if not is_token_valid():
        refresh_tok = token.get("refresh_token")
        if refresh_tok:
            try:
                logger.info("Access token expired. Attempting automatic OAuth refresh...")
                token = refresh_access_token(refresh_tok)
            except Exception as e:
                logger.error("Auto-refresh failed: %s", e)
                raise SalesforceAuthError(
                    f"Salesforce session expired and auto-refresh failed ({e}). "
                    "Please log in again via Data Export."
                )
        else:
            raise SalesforceAuthError(
                "Salesforce session expired or not authenticated. "
                "Please login via the Data Export page first."
            )

    instance_url = token.get("instance_url", "").rstrip("/")
    if not instance_url:
        raise SalesforceAuthError("No instance URL found in stored Salesforce token.")

    return Salesforce(
        instance_url=instance_url,
        session_id=token["access_token"]
    )
