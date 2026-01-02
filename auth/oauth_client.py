# auth/oauth_client.py

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SF_CLIENT_ID = os.getenv("SF_CLIENT_ID")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET")
SF_REDIRECT_URI = os.getenv("SF_REDIRECT_URI")
SF_LOGIN_URL = os.getenv("SF_LOGIN_URL")


def exchange_code_for_token(auth_code: str) -> dict:
    """
    Exchange OAuth authorization code for access token.
    """

    token_url = f"{SF_LOGIN_URL}/services/oauth2/token"

    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": SF_CLIENT_ID,
        "client_secret": SF_CLIENT_SECRET,
        "redirect_uri": SF_REDIRECT_URI,
    }

    response = requests.post(token_url, data=payload)

    if response.status_code != 200:
        raise Exception(
            f"Failed to get token: {response.status_code} - {response.text}"
        )

    return response.json()