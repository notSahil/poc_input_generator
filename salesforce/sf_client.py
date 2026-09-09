"""Bridge: Create a simple-salesforce Salesforce instance from stored OAuth token."""

import logging
from simple_salesforce import Salesforce

from core.exceptions import SalesforceAuthError
from salesforce.auth import is_token_valid, load_token, refresh_access_token

logger = logging.getLogger(__name__)


def get_sf_connection(profile: str | None = None) -> Salesforce:
    """
    Return a ready-to-use simple-salesforce Salesforce instance
    using the existing OAuth token from .sf_auth.json (or profile-specific token).
    Automatically attempts token refresh if the access token has expired.

    Raises:
        SalesforceAuthError: If user is not authenticated or token refresh fails.
    """
    token = load_token(profile=profile) if profile is not None else load_token()
    if not token or "access_token" not in token:
        raise SalesforceAuthError("No valid Salesforce token found. Please login first.")

    # Check validity and attempt auto-refresh if needed
    is_valid = is_token_valid(profile=profile) if profile is not None else is_token_valid()
    if not is_valid:
        refresh_tok = token.get("refresh_token")
        if refresh_tok:
            try:
                logger.info("Access token expired. Attempting automatic OAuth refresh...")
                token = refresh_access_token(refresh_tok, profile=profile) if profile is not None else refresh_access_token(refresh_tok)
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
