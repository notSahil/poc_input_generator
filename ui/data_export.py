# ui/data_export.py

import streamlit as st
import os
import threading
import webbrowser

from auth.oauth_server import start_oauth_server
from auth.token_store import load_token, clear_token

from salesforce.userinfo import get_user_info
from salesforce.metadata import list_objects


def render(go_home):
    st.subheader("📤 Data Export")

    # ==================================================
    # AUTH CHECK
    # ==================================================
    token = load_token()

    if not token:
        st.info("You must login with Salesforce to continue.")

        if st.button("🔐 Login with Salesforce", key="sf_login"):
            login_url = (
                 "https://login.salesforce.com/services/oauth2/authorize"
                f"?response_type=code"
                f"&client_id={os.getenv('SF_CLIENT_ID')}"
                f"&redirect_uri={os.getenv('SF_REDIRECT_URI')}"
                
            )

            threading.Thread(
                target=start_oauth_server,
                daemon=True
            ).start()

            webbrowser.open(login_url)
            st.warning("Complete login in browser, then return here.")
            st.stop()

        st.button("⬅ Back to Home", on_click=go_home, key="export_back_home")
        return

    # ==================================================
    # USER & ORG INFO
    # ==================================================
    try:
        try:
            user_info = get_user_info()
        except Exception as e:
            if "Bad_OAuth_Token" in str(e) or "403" in str(e):
                clear_token()
                st.error("Session expired. Please login again.")
                st.stop()
        else:
            raise

        st.subheader("🔐 Connected Salesforce User")

        col1, col2 = st.columns(2)

        with col1:
            st.text(f"Username: {user_info.get('preferred_username')}")
            st.text(f"User ID: {user_info.get('user_id')}")

        with col2:
            st.text(f"Org ID: {user_info.get('organization_id')}")
            st.text(
                f"Instance URL: {user_info.get('urls', {}).get('custom_domain')}"
            )

    except Exception as e:
        st.error(f"Failed to fetch user info: {e}")
        return

    # ==================================================
    # SALESFORCE OBJECTS
    # ==================================================
    st.subheader("📦 Available Salesforce Objects")

    try:
        objects = list_objects()

        object_df = [
            {
                "API Name": obj["name"],
                "Label": obj["label"],
                "Custom": obj["custom"]
            }
            for obj in objects
        ]

        st.dataframe(object_df, use_container_width=True)

    except Exception as e:
        st.error(f"Failed to load objects: {e}")
        return

    # ==================================================
    # ACTIONS
    # ==================================================
    st.success("✅ Salesforce connected")
    st.code(f"Instance: {token.get('instance_url')}")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("⬇️ Export Data", key="export_data"):
            st.info("Export logic will go here")

    with col2:
        if st.button("⬆️ Run Data Loader", key="export_loader"):
            st.info("Reuse existing engine here")

    st.divider()

    if st.button("🚪 Logout", key="export_logout"):
        clear_token()
        st.success("Logged out")
        st.stop()