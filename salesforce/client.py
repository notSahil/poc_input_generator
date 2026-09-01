"""Salesforce REST API client."""

import requests
from config import settings
from core.exceptions import SalesforceAPIError, SalesforceAuthError
from salesforce.auth import load_token


class SalesforceClient:
    def __init__(self):
        token = load_token()
        if not token or "access_token" not in token:
            raise SalesforceAuthError("Not authenticated with Salesforce. Please login first.")

        self.access_token = token["access_token"]
        self.instance_url = token.get("instance_url", "").rstrip("/")

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def get(self, path: str, params: dict | None = None) -> dict:
        """Generic GET request to Salesforce REST API."""
        url = f"{self.instance_url}{path}"
        response = requests.get(url, headers=self.headers, params=params)

        if response.status_code == 401:
            raise SalesforceAuthError("Salesforce session expired or invalid. Please login again.")

        if response.status_code >= 400:
            raise SalesforceAPIError(
                f"Salesforce API error ({response.status_code}): {response.text}",
                status_code=response.status_code
            )

        return response.json()