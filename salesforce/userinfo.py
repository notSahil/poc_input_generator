# salesforce/userinfo.py

import logging
from salesforce.client import SalesforceClient

logger = logging.getLogger(__name__)


def get_user_info(profile: str | None = None) -> dict:
    """
    Returns Salesforce user + org info for current token
    """
    client = SalesforceClient(profile=profile)
    return client.get("/services/oauth2/userinfo")


def get_extended_user_and_org_details(profile: str | None = None) -> dict:
    """
    Fetch comprehensive user and organization details for the active Salesforce session.
    Returns dictionary containing Name, Email, Username, Profile, Role, Org, Pod, Counts.
    """
    from salesforce.auth import get_active_profile, load_token
    from salesforce.sf_client import get_sf_connection

    prof = profile or get_active_profile()
    token = load_token(profile=prof) or {}

    data = {
        "profile": prof,
        "name": "N/A",
        "email": "N/A",
        "username": token.get("username", "Salesforce User"),
        "profile_name": "N/A",
        "role_name": "N/A",
        "timezone": "Europe/London",
        "org_name": "Sitetracker BT",
        "org_type": "Enterprise",
        "is_sandbox": prof in ("sandbox", "partial", "fullcopy"),
        "pod": "N/A",
        "org_id": "N/A",
        "instance_url": token.get("instance_url", "N/A"),
        "auth_method": "OAuth 2.0 (Auto-Refresh Active 🔄)" if token.get("refresh_token") else "Session Token (Workbench)",
    }

    try:
        u_info = get_user_info(profile=prof)
        if u_info:
            data["username"] = u_info.get("preferred_username") or u_info.get("username") or data["username"]
            data["org_id"] = u_info.get("organization_id", "N/A")
            data["email"] = u_info.get("email", "N/A")
            data["name"] = u_info.get("name", "N/A")
    except Exception as e:
        logger.debug("Could not get basic user info: %s", e)

    try:
        sf = get_sf_connection(profile=prof)
        org_res = sf.query("SELECT Id, Name, OrganizationType, IsSandbox, InstanceName FROM Organization LIMIT 1")
        if org_res.get("records"):
            org_rec = org_res["records"][0]
            data["org_name"] = org_rec.get("Name", data["org_name"])
            data["org_type"] = org_rec.get("OrganizationType", data["org_type"])
            data["is_sandbox"] = org_rec.get("IsSandbox", data["is_sandbox"])
            data["pod"] = org_rec.get("InstanceName", data["pod"])

        uname = data["username"].replace("'", "\\'")
        if uname:
            u_res = sf.query(
                f"SELECT Id, Name, Email, Username, Profile.Name, UserRole.Name, TimeZoneSidKey, LastLoginDate "
                f"FROM User WHERE Username = '{uname}' LIMIT 1"
            )
            if u_res.get("records"):
                u_rec = u_res["records"][0]
                data["name"] = u_rec.get("Name", data["name"])
                data["email"] = u_rec.get("Email", data["email"])
                if u_rec.get("Profile"):
                    data["profile_name"] = u_rec["Profile"].get("Name", "N/A")
                if u_rec.get("UserRole"):
                    data["role_name"] = u_rec["UserRole"].get("Name", "N/A")
                data["timezone"] = u_rec.get("TimeZoneSidKey", data["timezone"])
    except Exception as ex:
        logger.debug("Could not get extended user and org details: %s", ex)

    return data