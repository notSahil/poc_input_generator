"""Salesforce metadata operations."""

from config import settings
from salesforce.client import SalesforceClient


def list_objects(api_version: str | None = None) -> list[dict]:
    """Returns list of available Salesforce objects."""
    version = api_version or settings.SF_API_VERSION
    client = SalesforceClient()
    data = client.get(f"/services/data/{version}/sobjects")
    return data.get("sobjects", [])