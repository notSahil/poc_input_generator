from salesforce.client import SalesforceClient


def list_objects(api_version="v59.0"):
    """
    Returns list of available Salesforce objects
    """
    client = SalesforceClient()
    data = client.get(f"/services/data/{api_version}/sobjects")

    return data.get("sobjects", [])