"""Bridge: Create a simple-salesforce Salesforce instance from stored OAuth token."""

import logging
from simple_salesforce import Salesforce

from core.exceptions import SalesforceAuthError
from salesforce.auth import is_token_valid, load_token

logger = logging.getLogger(__name__)


def get_sf_connection() -> Salesforce:
    """
    Return a ready-to-use simple-salesforce Salesforce instance
    using the existing OAuth token from .sf_auth.json.

    Raises:
        SalesforceAuthError: If user is not authenticated or token is expired/invalid.
    """
    if not is_token_valid():
        raise SalesforceAuthError(
            "Salesforce session expired or not authenticated. "
            "Please login via the Data Export page first."
        )

    token = load_token()
    if not token or "access_token" not in token:
        raise SalesforceAuthError("No valid Salesforce token found.")

    instance_url = token.get("instance_url", "").rstrip("/")
    if not instance_url:
        raise SalesforceAuthError("No instance URL found in stored Salesforce token.")

    return Salesforce(
        instance_url=instance_url,
        session_id=token["access_token"]
    )
