# salesforce/userinfo.py

from salesforce.client import SalesforceClient


def get_user_info(profile: str | None = None):
    """
    Returns Salesforce user + org info for current token
    """
    client = SalesforceClient(profile=profile)
    return client.get("/services/oauth2/userinfo")