# salesforce/userinfo.py

from salesforce.client import SalesforceClient


def get_user_info():
    """
    Returns Salesforce user + org info for current token
    """
    client = SalesforceClient()
    return client.get("/services/oauth2/userinfo")