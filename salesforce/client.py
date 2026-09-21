"""Salesforce REST API client."""

import logging
import requests
from config import settings
from core.exceptions import SalesforceAPIError, SalesforceAuthError
from salesforce.auth import get_active_profile, load_token, refresh_access_token

logger = logging.getLogger(__name__)


class SalesforceClient:
    def __init__(self, profile: str | None = None):
        self.profile = profile or get_active_profile()
        token = load_token(self.profile)
        if not token or "access_token" not in token:
            raise SalesforceAuthError("Not authenticated with Salesforce. Please login first.")

        self.access_token = token["access_token"]
        self.instance_url = token.get("instance_url", "").rstrip("/")
        self.refresh_token_str = token.get("refresh_token")

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def _refresh_and_update(self) -> bool:
        """Attempt to refresh access token using stored refresh token."""
        if not self.refresh_token_str:
            return False
        try:
            logger.info("SalesforceClient attempting automatic OAuth token refresh for %s...", self.profile)
            new_token = refresh_access_token(self.refresh_token_str, profile=self.profile)
            self.access_token = new_token["access_token"]
            if "instance_url" in new_token and new_token["instance_url"]:
                self.instance_url = new_token["instance_url"].rstrip("/")
            if "refresh_token" in new_token and new_token["refresh_token"]:
                self.refresh_token_str = new_token["refresh_token"]
            self.headers["Authorization"] = f"Bearer {self.access_token}"
            return True
        except Exception as e:
            logger.warning("SalesforceClient auto-refresh failed: %s", e)
            return False

    def get(self, path: str, params: dict | None = None, timeout: float = 8.0) -> dict:
        """Generic GET request to Salesforce REST API with auto-refresh on 401."""
        url = f"{self.instance_url}{path}"
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
            raise SalesforceAPIError(f"Network error communicating with Salesforce: {net_err}") from net_err

        if response.status_code in (401, 403):
            if self._refresh_and_update():
                retry_url = f"{self.instance_url}{path}"
                try:
                    response = requests.get(retry_url, headers=self.headers, params=params, timeout=timeout)
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as net_err:
                    raise SalesforceAPIError(f"Network error communicating with Salesforce: {net_err}") from net_err

        if response.status_code in (401, 403):
            raise SalesforceAuthError("Salesforce session expired or invalid. Please login again.")

        if response.status_code >= 400:
            raise SalesforceAPIError(
                f"Salesforce API error ({response.status_code}): {response.text}",
                status_code=response.status_code
            )

        return response.json()