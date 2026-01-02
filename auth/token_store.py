# auth/token_store.py

import json
import os

TOKEN_FILE = ".sf_auth.json"


def save_token(token_data: dict):
    """
    Save Salesforce OAuth token locally.
    This file must NEVER be committed to git.
    """
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)


def load_token() -> dict | None:
    """
    Load stored Salesforce token if exists.
    """
    if not os.path.exists(TOKEN_FILE):
        return None

    with open(TOKEN_FILE, "r") as f:
        return json.load(f)


def clear_token():
    """
    Logout / clear stored token.
    """
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)