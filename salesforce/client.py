# salesforce/client.py

import requests
from auth.token_store import load_token


class SalesforceClient:
    def __init__(self):
        token = load_token()
        if not token:
            raise RuntimeError("Not authenticated with Salesforce")

        self.access_token = token["access_token"]
        self.instance_url = token["instance_url"]

        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

    def get(self, path: str, params=None):
        """
        Generic GET request to Salesforce REST API
        """
        url = f"{self.instance_url}{path}"
        response = requests.get(url, headers=self.headers, params=params)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Salesforce API error {response.status_code}: {response.text}"
            )

        return response.json()